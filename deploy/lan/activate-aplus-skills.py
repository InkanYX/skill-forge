"""Activate only the reviewed bundled A+ releases; never rewrite project snapshots."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import SkillPackage, SkillVersion, make_engine, database_url
from app.skill_packages import seed_builtin
from app.skill_store import content_fingerprint, file_entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    storage = Path(os.environ['SKILL_FORGE_DATA_DIR'])
    root = Path(__file__).resolve().parents[2] / 'backend/resources/builtin-skills'
    names = ('premium-product-image-workflow', 'amazon-a-plus')
    engine = make_engine(database_url())
    try:
        if args.activate:
            seed_builtin(engine, storage)
        result = []
        with Session(engine) as session, session.begin():
            for name in names:
                package = session.scalar(select(SkillPackage).where(
                    SkillPackage.name == name, SkillPackage.source == 'builtin'))
                fingerprint = content_fingerprint(file_entries(root / name))
                version = session.scalar(select(SkillVersion).where(
                    SkillVersion.skill_id == package.id, SkillVersion.content_sha256 == fingerprint)) if package else None
                if args.activate and not version:
                    raise RuntimeError('Reviewed skill version not installed: ' + name)
                if args.activate:
                    package.current_version_id = version.id
                result.append({'name': name, 'installed': version is not None,
                    'version': version.version_label if version else None,
                    'active': bool(version and package.current_version_id == version.id)})
        print(json.dumps({'activated': args.activate, 'skills': result}, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
