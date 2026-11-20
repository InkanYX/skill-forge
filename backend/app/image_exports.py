"""Bounded local ZIP exports. No model calls and no credential columns."""
import csv
import io
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.database import ImageJob, CreativeCase
from app.image_provider import MAX_IMAGE

MAX_EXPORT_IMAGES = 50
MAX_EXPORT_BYTES = 200 * 1024 * 1024
PNG_HEADER = b'\x89PNG\r\n\x1a\n'


def safe_name(value: str, fallback='image') -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:50].rstrip(' .') or fallback
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', value, re.I):
        value = '_' + value
    return value


def csv_cell(value):
    value = str(value or '')
    # A prompt or SKU must not become a formula when opened in Excel.
    if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value


def build_archive(rows, directory: Path, include_records=True):
    output = tempfile.TemporaryFile(mode='w+b')
    try:
        records, total = [], 0
        with ZipFile(output, mode='w', compression=ZIP_DEFLATED, compresslevel=1) as archive:
            for index, (job, case) in enumerate(rows, start=1):
                path = directory / 'image-jobs' / str(UUID(job.id)) / 'result.png'
                product = json.loads(job.product_snapshot or '{}')
                template = json.loads(job.template_snapshot or '{}')
                sku = safe_name(product.get('sku', ''), 'product')
                purpose = safe_name(job.shot_name or template.get('name', ''), 'image')
                filename = f'images/{index:03d}_{sku}_{purpose}_{job.id[:8]}.png'
                try:
                    with path.open('rb') as source:
                        header = source.read(8)
                        if header != PNG_HEADER:
                            raise HTTPException(409, '部分图片文件不可用，请在作品详情检查后重新选择。')
                        size = len(header)
                        total += size
                        with archive.open(filename, 'w') as target:
                            target.write(header)
                            while chunk := source.read(64 * 1024):
                                size += len(chunk); total += len(chunk)
                                if size > MAX_IMAGE or total > MAX_EXPORT_BYTES:
                                    raise HTTPException(413, '导出超出限制：单张最多 20 MB，每次合计最多 200 MB，请减少图片。')
                                target.write(chunk)
                except OSError:
                    raise HTTPException(409, '部分图片文件缺失或无法读取，请在作品详情检查后重新选择。') from None
                records.append({
                    'file': filename, 'job_id': job.id, 'created_at': job.created_at,
                    'model_name': job.model_name, 'requested_size': job.size, 'mode': job.mode,
                    'prompt': job.prompt, 'product': product, 'template': template,
                    'parent_job_id': job.parent_job_id, 'edit_instruction': job.edit_instruction,
                    'set_id': job.set_id, 'set_name': job.set_name, 'shot_name': job.shot_name,
                    'case': {'title': case.title, 'experience': case.experience, 'issues': case.issues} if case else None,
                })
            if include_records:
                manifest = {'format_version': 1, 'exported_at': datetime.now(timezone.utc).isoformat(), 'image_count': len(records), 'items': records}
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
                csv_output = io.StringIO(newline='')
                writer = csv.writer(csv_output)
                writer.writerow(['图片文件', '任务ID', 'SKU', '套图名称', '图片用途', '模型', '创建时间', '制作要求', '修改要求', '案例经验'])
                for row in records:
                    writer.writerow([csv_cell(value) for value in [row['file'], row['job_id'], row['product'].get('sku', ''), row['set_name'], row['shot_name'], row['model_name'], row['created_at'], row['prompt'], row['edit_instruction'], (row['case'] or {}).get('experience', '')]])
                archive.writestr('制作记录.csv', csv_output.getvalue().encode('utf-8-sig'))
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise


def build_export_router(engine, directory: Path):
    router = APIRouter(prefix='/api/image-jobs', tags=['image-exports'])

    @router.post('/exports')
    def export_images(job_ids: Annotated[str, Form(max_length=2500)] = '', set_id: Annotated[UUID | None, Form()] = None, include_records: Annotated[bool, Form()] = True):
        if engine is None:
            raise HTTPException(503, '请先配置数据库。')
        if bool(job_ids) == bool(set_id):
            raise HTTPException(422, '请选择作品或指定一套图片。')
        identifiers = []
        if job_ids:
            try:
                values = json.loads(job_ids)
                if not isinstance(values, list) or not 1 <= len(values) <= MAX_EXPORT_IMAGES:
                    raise ValueError()
                identifiers = list(dict.fromkeys(str(UUID(value)) for value in values))
            except (ValueError, TypeError, AttributeError):
                raise HTTPException(422, '每次请选择 1–50 张已完成图片。') from None
        with Session(engine) as session:
            query = select(ImageJob, CreativeCase).outerjoin(CreativeCase, CreativeCase.job_id == ImageJob.id)
            if set_id:
                rows = list(session.execute(query.where(ImageJob.set_id == str(set_id), ImageJob.status == 'succeeded').order_by(ImageJob.shot_index, ImageJob.created_at, ImageJob.id).limit(MAX_EXPORT_IMAGES + 1)))
                if len(rows) > MAX_EXPORT_IMAGES:
                    raise HTTPException(413, '这套已完成图片超过 50 张，请到作品库分批勾选导出。')
            else:
                found = {row[0].id: row for row in session.execute(query.where(ImageJob.id.in_(identifiers)))}
                if len(found) != len(identifiers):
                    raise HTTPException(404, '部分作品不存在，请刷新列表后重新选择。')
                rows = [found[identifier] for identifier in identifiers]
            if not rows:
                raise HTTPException(422, '当前没有可导出的已完成图片。')
            if any(job.status != 'succeeded' for job, _ in rows):
                raise HTTPException(409, '仅能导出已完成图片，请取消选择未完成任务。')
            archive = build_archive(rows, directory, include_records)
        def chunks():
            try:
                while chunk := archive.read(64 * 1024):
                    yield chunk
            finally:
                archive.close()
        archive.seek(0, 2); length = archive.tell(); archive.seek(0)
        return StreamingResponse(chunks(), media_type='application/zip', headers={
            'Content-Disposition': f'attachment; filename="skill-forge-images-{uuid4().hex[:8]}.zip"',
            'Content-Length': str(length), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Export-Count': str(len(rows)),
        }, background=BackgroundTask(archive.close))
    return router
