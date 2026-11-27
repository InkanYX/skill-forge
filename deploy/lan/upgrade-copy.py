"""Clone the old deployment, then adapt its migration fork without changing it."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
OLD = Path('D:/project/skill-forge')
RUNTIME = ROOT / '.lan-runtime'
TARGET = 'skill_forge_lan_v2'
sys.path.insert(0, str(ROOT / 'backend'))
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text, select, func
from sqlalchemy.engine import make_url
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def execute(*args):
    subprocess.run(args, check=True, capture_output=True)


def run_revision(connection, filename):
    path = ROOT / 'backend/migrations/versions' / filename
    spec = importlib.util.spec_from_file_location('deployment_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()
    print('Applied', module.revision)


def migrate(engine):
    with engine.begin() as connection:
        revision = connection.scalar(text('select version_num from alembic_version'))
        if revision != '0018_product_image_projects':
            raise RuntimeError('Unexpected source migration revision: ' + str(revision))
        # Apply the alternate 0017, keeping every old column and table.
        run_revision(connection, '0017_creation_conversations.py')
        # Alternate 0018/0019 overlap columns already introduced by the old fork.
        # Add their remaining fields without overwriting user-selected model IDs.
        with Operations.context(MigrationContext.configure(connection)) as operation:
            for name in ('request_parameters','text_parameters','vision_parameters','capabilities'):
                operation.add_column('image_configurations', sa.Column(name, sa.Text(), nullable=False, server_default='{}'))
            for name, default in (('generation_path','/images/generations'),('edit_path','/images/edits')):
                operation.add_column('image_configurations', sa.Column(name, sa.String(300), nullable=False, server_default=default))
            operation.add_column('image_configurations', sa.Column('model_settings',sa.Text(),nullable=False,server_default='{}'))
            operation.add_column('image_configurations', sa.Column('auto_review',sa.Boolean(),nullable=False,server_default=sa.false()))
        connection.execute(text('update image_configurations set request_parameters=:parameters'),
                           {'parameters':json.dumps({'quality':'high','size':'auto','output_format':'png'})})
        print('Adapted alternate 0018/0019 while preserving model selections.')
        for filename in ('0020_guided_creation.py','0021_product_planning.py','0022_image_feedback.py',
                         '0023_image_trash.py','0024_workflow_cases.py','0025_team_sharing.py'):
            run_revision(connection, filename)
        connection.execute(text("update image_configurations set image_model_name=model_name, planning_model_name=text_model_name"))
        # Only record the new revision after all of its operations have succeeded.
        connection.execute(text('update alembic_version set version_num=:version'), {'version':'0025_team_sharing'})


def main():
    original = dotenv_values(OLD / 'backend/.env')
    old_url = make_url(original['DATABASE_URL'])
    if old_url.database != 'skill_forge':
        raise RuntimeError('Unexpected source database; no database was changed.')
    engine = create_engine(old_url, hide_parameters=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_dir = RUNTIME / 'backups' / stamp
    backup_dir.mkdir(parents=True)
    container = json.loads(subprocess.check_output(['docker','inspect','skill-forge-postgres']))[0]
    env = dict(item.split('=',1) for item in container['Config']['Env'] if '=' in item)
    postgres_user = env.get('POSTGRES_USER','postgres')
    with engine.connect() as connection:
        active = sum(connection.scalar(text('select count(*) from '+table+' where status in (:a,:b)'),
                                       {'a':'queued','b':'running'}) for table in ('image_jobs','agent_runs','product_image_projects'))
        if active:
            raise RuntimeError('Business jobs are active; no database was changed.')
        tables = inspect(connection).get_table_names()
        counts = {table:connection.scalar(text('select count(*) from "'+table+'"')) for table in tables}
    dumpname = 'before-directory-upgrade-'+stamp+'.dump'
    execute('docker','exec','skill-forge-postgres','pg_dump','-U',postgres_user,'-d',old_url.database,'-Fc','-f','/tmp/'+dumpname)
    execute('docker','cp','skill-forge-postgres:/tmp/'+dumpname,str(backup_dir/dumpname))
    source_data = Path(original.get('SKILL_FORGE_DATA_DIR') or OLD/'backend/data')
    shutil.make_archive(str(backup_dir/'data'), 'zip', source_data)
    shutil.copy2(OLD/'backend/.env', backup_dir/'backend.env')
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        if connection.scalar(text('select 1 from pg_database where datname=:name'),{'name':TARGET}):
            raise RuntimeError('Target database already exists; refusing to overwrite it.')
        connection.execute(text('CREATE DATABASE '+TARGET))
    execute('docker','exec','skill-forge-postgres','pg_restore','-U',postgres_user,'-d',TARGET,'--exit-on-error','/tmp/'+dumpname)
    target_url = old_url.set(database=TARGET)
    target_engine = create_engine(target_url, hide_parameters=True)
    migrate(target_engine)
    from app.database import Base
    with target_engine.connect() as connection:
        # Query every mapped column to catch schema mismatches before switching.
        for table in Base.metadata.sorted_tables:
            connection.execute(select(table).limit(1)).first()
        for table, count in counts.items():
            if table == 'alembic_version': continue
            actual = connection.scalar(text('select count(*) from "'+table+'"'))
            if actual != count:
                raise RuntimeError('Row preservation check failed for '+table)
    target_data = RUNTIME/'shared-data'
    if target_data.exists():
        raise RuntimeError('Deployment data directory already exists; refusing to overwrite it.')
    shutil.copytree(source_data, target_data)
    for source in source_data.rglob('*'):
        if source.is_file() and source.read_bytes() != (target_data/source.relative_to(source_data)).read_bytes():
            raise RuntimeError('Copied data differs: '+str(source.relative_to(source_data)))
    deployment = {'DATABASE_URL':target_url.render_as_string(hide_password=False),'SKILL_FORGE_DATA_DIR':str(target_data)}
    (RUNTIME/'deployment.env').write_text(''.join(k+'='+json.dumps(v)+'\n' for k,v in deployment.items()),encoding='utf-8')
    report = {'source_database':old_url.database,'target_database':TARGET,'revision':'0025_team_sharing',
              'backup':str(backup_dir),'row_counts':counts,'data_dir':str(target_data),
              'legacy_projects_preserved_in':'product_image_projects'}
    (RUNTIME/'upgrade-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    target_engine.dispose()
    engine.dispose()
    print(json.dumps(report))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Avoid echoing credentials from driver exceptions or command arguments.
        print('Upgrade failed:', type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
