"""Deterministic business rules. No model can supply metric values."""
import csv
import io
from datetime import date, datetime
from .db import TZ


class BusinessError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def require(condition, message, code='INPUT_INVALID', status=400, details=None):
    if not condition:
        raise BusinessError(status, code, message, details)


def text(value, label, limit=2000):
    require(isinstance(value,str) and 0<len(value.strip())<=limit, f'{label}必填，且不超过 {limit} 字')
    return value.strip()


def parse_date(value):
    require(isinstance(value,str), '日期格式应为 YYYY-MM-DD')
    try:
        parsed = date.fromisoformat(value)
        require(parsed.isoformat()==value,'日期格式应为 YYYY-MM-DD')
        return parsed
    except ValueError:
        raise BusinessError(400,'INPUT_INVALID','日期格式应为 YYYY-MM-DD')


def local_date(value):
    if not value:
        return None
    if len(value)==10:
        return date.fromisoformat(value)
    dt = datetime.fromisoformat(value.replace('Z','+00:00'))
    return dt.astimezone(TZ).date() if dt.tzinfo else dt.date()


def compute_metrics(rows, cutoff, start, end):
    active = [r for r in rows if r['status']!='CANCELLED']
    done = [r for r in active if r['status']=='DONE' and (not r.get('completed_at') or local_date(r['completed_at'])<=cutoff)]
    done_ids = {r['task_id'] for r in done}
    pending = [r for r in active if r['task_id'] not in done_ids]
    overdue = [{**r, 'overdue_days':(cutoff-local_date(r['due_date'])).days} for r in pending if r.get('due_date') and local_date(r['due_date'])<cutoff]
    missing = []
    if any(not r.get('due_date') for r in pending):
        missing.append('部分未完成任务缺截止日，未纳入可判定逾期样本。')
    if any(not r.get('completed_at') for r in done):
        missing.append('部分已完成任务缺完成时间，不计入本期完成数。')
    if not any(r.get('milestone_id') for r in active):
        missing.append('缺少里程碑计划与依赖数据，无法判断关键路径或升级风险等级。')
    missing += ['未接入会议纪要及企业文档，延期原因无法确认。','缺少上期期末快照，不提供上期变化。']
    return dict(total=len(active), completed=len(done), completion_rate=round(len(done)*100/len(active),2) if active else None, period_completed=sum(bool(r.get('completed_at')) and start<=local_date(r['completed_at'])<=min(end,cutoff) for r in done), overdue_count=len(overdue), overdue_tasks=overdue, completed_late=sum(bool(r.get('due_date')) and bool(r.get('completed_at')) and local_date(r['completed_at'])>local_date(r['due_date']) for r in done), missing=missing)


CSV_FIELDS = ['task_id','title','owner_id','status','planned_start','due_date','completed_at','milestone_id','updated_at']


def validate_csv(content, member_ids):
    require(isinstance(content,str) and len(content.encode())<=4_000_000,'CSV 不能超过 4 MB')
    reader = csv.DictReader(io.StringIO(content.lstrip('\ufeff')), strict=True)
    require(reader.fieldnames and {'task_id','title','status'}<=set(reader.fieldnames),'CSV 缺少 task_id、title 或 status 表头')
    rows, errors, seen = [], [], set()
    try:
        for line, raw in enumerate(reader,2):
            require(line<=10001,'每批最多 10000 行')
            try:
                require(None not in raw and all(v is not None for v in raw.values()), '列数与表头不一致')
                row = {f:(raw.get(f) or '').strip() for f in CSV_FIELDS}
                text(row['task_id'],'任务编号',100)
                text(row['title'],'任务标题',200)
                require(row['task_id'] not in seen,'批次内任务编号重复')
                require(row['status'] in {'TODO','IN_PROGRESS','DONE','CANCELLED'},'未知任务状态')
                require(not row['owner_id'] or row['owner_id'] in member_ids,'负责人不是有效项目成员')
                for field in ['planned_start','due_date','completed_at','updated_at']:
                    if row[field]:
                        local_date(row[field])
                require(not(row['planned_start'] and row['completed_at']) or local_date(row['completed_at'])>=local_date(row['planned_start']), '完成时间早于开始时间')
                seen.add(row['task_id'])
                rows.append(row)
            except (BusinessError,ValueError,TypeError) as exc:
                errors.append(dict(line=line,task_id=raw.get('task_id',''),message=exc.message if isinstance(exc,BusinessError) else '日期格式无效'))
    except csv.Error:
        raise BusinessError(400,'INPUT_INVALID','CSV 引号或分隔格式无效')
    require(rows or errors,'CSV 中没有数据行')
    return rows, errors
