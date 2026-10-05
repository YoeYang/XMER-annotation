"""Local-only CPM prototype. Independent SQLite, no VA imports or connections."""
import argparse
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
SCHEMA = 'cpm-2026-10-05-v1-candidate'
ANNOTATORS = ('CPM-01', 'CPM-02')
MODALITIES = ('face', 'body', 'audio', 'text')


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS samples (
            clip_id TEXT PRIMARY KEY, subset_id TEXT NOT NULL,
            source TEXT NOT NULL, va_clip_id TEXT, selection_metadata TEXT NOT NULL,
            original_card TEXT NOT NULL, duration REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS assignments (
            task_id TEXT PRIMARY KEY, clip_id TEXT NOT NULL REFERENCES samples,
            annotator_id TEXT NOT NULL CHECK(annotator_id IN ('CPM-01','CPM-02')),
            UNIQUE(clip_id,annotator_id));
          CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES assignments,
            attempt_no INTEGER NOT NULL, schema_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('draft','submitted')),
            payload TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(task_id,attempt_no));
        ''')
        cards = [
            dict(subject='画面中的队长', event='队伍输掉比赛，队长接受赛后采访', goal='赢得比赛；准备下一场比赛', role='队长，与采访者交谈', quote='我们输了，但仍要尊重对手；下一场会调整战术。'),
            dict(subject='正在发言的项目成员', event='项目提案得到采纳，成员介绍后续安排', goal='推进提案实施', role='项目成员，与同事交谈', quote='方案通过了，我们下周可以开始准备。'),
            dict(subject='画面右侧的说话者', event='对话提到一项结果，片段未说明具体内容', goal='', role='', quote='好吧，我知道了。'),
        ]
        for index in range(360):
            clip = f'CPM-S{index + 1:04d}'
            card = cards[index % len(cards)]
            db.execute('INSERT OR IGNORE INTO samples VALUES (?,?,?,?,?,?,?)',
                       (clip, 'CPM-DEMO-360', 'mock', None,
                        json.dumps({'method': 'mock', 'future_source': 'VA selection manifest'}, ensure_ascii=False),
                        json.dumps(card, ensure_ascii=False), 12.0))
            for annotator in ANNOTATORS:
                db.execute('INSERT OR IGNORE INTO assignments VALUES (?,?,?)',
                           (f'{annotator}:{clip}', clip, annotator))


def validate(payload, duration):
    errors = []
    def window(value, label):
        if not isinstance(value, list) or len(value) != 2 or any(type(n) not in (int, float) for n in value) or not (0 <= value[0] < value[1] <= duration):
            errors.append(f'{label}须满足 0 ≤ 开始 < 结束 ≤ {duration} 秒')
    window(payload.get('score_window'), '评分区间')
    card = payload.get('card', {})
    checks = payload.get('checks', {})
    if not card.get('subject', '').strip() or checks.get('subject') != 'confirmed':
        errors.append('请核对目标主体')
    for field in ('event', 'goal', 'role'):
        if checks.get(field) not in ('confirmed', 'unknown'):
            errors.append(f'请核对场景字段 {field}')
        if checks.get(field) == 'confirmed' and not card.get(field, '').strip():
            errors.append(f'已确认的 {field} 不能为空')
    if payload.get('event_location') not in ('inside', 'outside', 'unknown'):
        errors.append('请核对事件时间')
    if payload.get('event_location') == 'inside':
        window(payload.get('event_window'), '事件区间')
    evidence = payload.get('evidence', [])
    ids = [e.get('id') for e in evidence]
    if len(ids) != len(set(ids)):
        errors.append('证据编号不能重复')
    verified = {e['id']: e for e in evidence if e.get('verified') and e.get('observation', '').strip()}
    for item in verified.values():
        window(item.get('span'), f"证据 {item['id']}")
    def ratings(values):
        for dim in 'RICN':
            rating = values.get(dim, {})
            state = rating.get('state')
            if state == 'unknown':
                if rating.get('value') is not None:
                    errors.append(f'{dim} 信息不足必须保存为空值')
            elif state == 'known':
                if type(rating.get('value')) is not int or rating['value'] not in (-2, -1, 0, 1, 2):
                    errors.append(f'{dim} 评分无效')
                refs = rating.get('evidence_ids', [])
                if not refs or any(ref not in verified for ref in refs):
                    errors.append(f'{dim} 请关联已核对的依据')
            else:
                errors.append(f'请选择 {dim} 分数或信息不足')
            if rating.get('mixed') and not rating.get('note', '').strip():
                errors.append(f'{dim} 混合评价需要说明')
    ratings(payload.get('ratings', {}))
    conflict = payload.get('conflict', {})
    if conflict.get('status') not in ('confirmed', 'not_confirmed', 'uncertain'):
        errors.append('请选择冲突核对结论')
    if conflict.get('status') == 'confirmed':
        window(conflict.get('reviewed_window'), '人工冲突区间')
        modalities = conflict.get('modalities', [])
        if len(set(modalities)) < 2 or any(m not in MODALITIES for m in modalities):
            errors.append('明确冲突至少选择两个通道')
        for modality in modalities:
            if not any(e.get('modality') == modality for e in verified.values()):
                errors.append(f'{modality} 缺少已核对的时间证据')
    constraint = payload.get('constraint', {})
    if constraint.get('status') not in ('present', 'absent', 'unknown'):
        errors.append('请选择表达约束状态')
    if constraint.get('status') == 'present' and not any(i in verified for i in constraint.get('evidence_ids', [])):
        errors.append('表达约束需要已核对依据')
    dynamic = payload.get('dynamic', {})
    if dynamic.get('status') not in ('changed', 'unchanged', 'unknown'):
        errors.append('请选择表达是否变化')
    if dynamic.get('status') == 'changed':
        time = dynamic.get('time')
        if type(time) not in (int, float) or not 0 <= time <= duration:
            errors.append('变化时间超出片段')
        if not dynamic.get('modalities') or any(m not in MODALITIES for m in dynamic.get('modalities', [])) or not dynamic.get('description', '').strip():
            errors.append('请填写变化通道和描述')
        if dynamic.get('updated_ratings') is not None:
            window(dynamic.get('score_window'), '变化后评分区间')
            changed_window = dynamic.get('score_window')
            if isinstance(changed_window, list) and len(changed_window) == 2 and type(changed_window[0]) in (int, float) and type(time) in (int, float) and changed_window[0] < time:
                errors.append('变化后评分区间不能早于变化时间')
            ratings(dynamic['updated_ratings'])
    return errors


def save_record(db, annotator, clip, status, payload):
    if annotator not in ANNOTATORS or status not in ('draft', 'submitted') or not isinstance(payload, dict):
        raise ValueError('标注者、状态或记录无效')
    task_id = f'{annotator}:{clip}'
    sample = db.execute('SELECT s.* FROM samples s JOIN assignments a USING(clip_id) WHERE a.task_id=?', (task_id,)).fetchone()
    if not sample:
        raise ValueError('样本未分配给该标注者')
    if payload.get('schema_version') != SCHEMA or payload.get('anchor_version') != SCHEMA:
        raise ValueError('量表或数据版本不匹配')
    if payload.get('subject_id') != f'{clip}:subject-1' or payload.get('event_id') != f'{clip}:event-1' or payload.get('modality') != 'audiovisual':
        raise ValueError('主体、事件或模态编号不匹配')
    candidate = payload.get('conflict', {})
    if candidate.get('candidate_window') != [2.4, 4.8] or candidate.get('candidate_source') != 'mock-candidate-v1':
        raise ValueError('原始候选窗口及来源不可修改；请调整人工核对窗口')
    errors = validate(payload, sample['duration']) if status == 'submitted' else []
    if errors:
        raise ValueError('；'.join(errors))
    db.execute('BEGIN IMMEDIATE')
    previous = db.execute('SELECT * FROM records WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1', (task_id,)).fetchone()
    if previous and previous['status'] == 'submitted' and not payload.get('revision_reason', '').strip():
        raise ValueError('修改已提交记录需要修订原因')
    attempt = previous['attempt_no'] + 1 if previous else 1
    db.execute('INSERT INTO records(task_id,attempt_no,schema_version,status,payload,created_at) VALUES(?,?,?,?,?,?)',
               (task_id, attempt, SCHEMA, status, json.dumps(payload, ensure_ascii=False, allow_nan=False), datetime.now(timezone.utc).isoformat()))
    db.commit()
    return {'attempt_no': attempt, 'status': status}


class Handler(BaseHTTPRequestHandler):
    def respond(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == '/cpm-api/demo.mp4':
            media = ROOT.parent / 'public/media/audiovisual.mp4'
            body = media.read_bytes()
            start, end = 0, len(body) - 1
            header = self.headers.get('Range')
            if header:
                try:
                    left, right = header.removeprefix('bytes=').split('-')
                    start, end = int(left or 0), int(right) if right else end
                    if not 0 <= start <= end < len(body):
                        raise ValueError()
                except ValueError:
                    self.send_error(416)
                    return
            self.send_response(206 if header else 200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            if header:
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(body)}')
            self.end_headers()
            self.wfile.write(body[start:end + 1])
            return
        with connect(self.server.db_path) as db:
            if url.path == '/cpm-api/samples':
                annotator = query.get('annotator', ['CPM-01'])[0]
                if annotator not in ANNOTATORS:
                    return self.respond({'error': '未知标注者'}, 400)
                rows = db.execute('''SELECT s.*, r.status, r.attempt_no FROM samples s
                    JOIN assignments a USING(clip_id)
                    LEFT JOIN records r ON r.id=(SELECT id FROM records WHERE task_id=a.task_id ORDER BY attempt_no DESC LIMIT 1)
                    WHERE a.annotator_id=? ORDER BY s.clip_id''', (annotator,)).fetchall()
                return self.respond([dict(row) | {'original_card': json.loads(row['original_card'])} for row in rows])
            if url.path == '/cpm-api/record':
                task = f"{query.get('annotator', [''])[0]}:{query.get('clip', [''])[0]}"
                row = db.execute('SELECT * FROM records WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1', (task,)).fetchone()
                return self.respond(dict(row) | {'payload': json.loads(row['payload'])} if row else None)
            if url.path == '/cpm-api/admin':
                counts = []
                for annotator in ANNOTATORS:
                    row = db.execute('''SELECT COUNT(*) AS total,
                        SUM(CASE WHEN r.status='submitted' THEN 1 ELSE 0 END) AS submitted,
                        SUM(CASE WHEN r.status='draft' THEN 1 ELSE 0 END) AS draft
                        FROM assignments a LEFT JOIN records r ON r.id=(SELECT id FROM records WHERE task_id=a.task_id ORDER BY attempt_no DESC LIMIT 1)
                        WHERE a.annotator_id=?''', (annotator,)).fetchone()
                    counts.append(dict(row) | {'annotator': annotator})
                recent = [dict(r) for r in db.execute('SELECT id,task_id,attempt_no,status,created_at FROM records ORDER BY id DESC LIMIT 30')]
                return self.respond({'counts': counts, 'recent': recent, 'schema': SCHEMA, 'sample_count': 360})
            if url.path == '/cpm-api/export':
                def rows(table):
                    return [dict(r) for r in db.execute(f'SELECT * FROM {table}')]
                records = rows('records')
                for row in records:
                    row['payload'] = json.loads(row['payload'])
                return self.respond({'schema_version': SCHEMA, 'mock': True, 'samples': rows('samples'), 'assignments': rows('assignments'), 'records': records})
        self.respond({'error': '接口不存在'}, 404)

    def do_POST(self):
        if self.path != '/cpm-api/record':
            return self.respond({'error': '接口不存在'}, 404)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1_000_000:
                raise ValueError('请求大小无效')
            data = json.loads(self.rfile.read(size))
            with connect(self.server.db_path) as db:
                result = save_record(db, data['annotator'], data['clip'], data['status'], data['payload'])
            self.respond(result)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self.respond({'error': str(error)}, 400)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, default=ROOT / 'data/cpm-demo.sqlite3')
    parser.add_argument('--port', type=int, default=5181)
    args = parser.parse_args()
    initialize(args.db)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.db_path = args.db
    print(f'CPM local API: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()
