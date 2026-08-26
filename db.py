import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "auto_sms.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number  TEXT NOT NULL,          -- 상대방 번호 (수신: 보낸 사람 / 발신: 받는 사람)
            contact_name  TEXT DEFAULT '',         -- 휴대폰 연결 앱에 저장된 이름(있으면)
            body          TEXT NOT NULL,
            direction     TEXT NOT NULL CHECK(direction IN ('in','out')),  -- in=수신, out=발신
            msg_time      TEXT,                    -- 문자 자체의 시각(휴대폰 연결 화면에 찍힌 시각)
            dedup_key     TEXT UNIQUE,              -- 워처가 같은 메시지를 중복 저장하지 않게 막는 키
            created_at    TEXT DEFAULT (datetime('now', 'localtime')),
            status        TEXT DEFAULT ''            -- 처리상태
        );
        CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone_number);
        CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

        CREATE TABLE IF NOT EXISTS templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,             -- 대시보드 드롭다운에 보일 이름 (예: "접수 확인 안내")
            body        TEXT NOT NULL,              -- 실제 발송될 문구
            sort_no     INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,               -- 예: auto_reply_enabled, auto_reply_template_id
            value TEXT
        );
    """)
    _migrate_message_columns(conn)
    conn.commit()
    conn.close()


# 민원 문자 목록에서 직원이 직접 채워 넣는 칸들 — 워처/자동화가 채우는 값이
# 아니라 사람이 보고 판단해서 입력하는 값이라 전부 빈 문자열 기본값으로 둔다.
# status(처리상태)는 미처리/처리중/처리완료 중 고르는 드롭다운 전용 컬럼이고,
# manual_input(입력)/receipt_no(접수번호)는 자유 텍스트다.
# thread_id는 같은 민원인이 시간차를 두고 다시 보내서 스레드가 갈라진 걸
# 체크박스로 골라 수동으로 합칠 때 쓴다 — 기본은 NULL이고(스레드 묶음은
# app.py의 _build_threads()가 번호+시간순으로 자동 계산), 병합된 메시지들만
# 같은 값(합친 메시지 중 가장 작은 id)을 공유하게 된다.
_MESSAGE_MANUAL_COLUMNS = {
    "status":       "TEXT DEFAULT ''",   # 처리상태
    "manual_input": "TEXT DEFAULT ''",   # 입력
    "receipt_no":   "TEXT DEFAULT ''",   # 접수번호
    "thread_id":    "INTEGER DEFAULT NULL",  # 수동 병합된 스레드 묶음 id
}


def _migrate_message_columns(conn):
    """CREATE TABLE IF NOT EXISTS만으론 기존에 이미 있던 messages 테이블에
    새 컬럼이 추가되지 않으므로 별도로 확인해서 붙인다."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
    for col, col_type in _MESSAGE_MANUAL_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {col_type}")


def get_setting(key: str, default: str = None) -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def make_dedup_key(phone_number: str, body: str, msg_time: str) -> str:
    """수신 워처가 같은 화면을 반복해서 훑을 때 같은 메시지를 또 저장하지
    않도록 막는 키. 시각까지 포함해서, 같은 번호로 같은 문구가 서로 다른
    시각에 여러 번 와도(예: 정형화된 자동응답) 별개 메시지로 취급한다."""
    return f"{phone_number}|{msg_time}|{body}"


def now_local() -> str:
    """messages.created_at에 쓸 현재 시각(로컬, 한국 기준) 문자열.

    SQLite의 CURRENT_TIMESTAMP는 UTC라서, 알림에서 시각(msg_time)을 못 읽어
    화면이 created_at으로 대체 표시할 때 실제 시각보다 9시간 전으로 보이는
    문제가 있었다. app.py의 INSERT에서 이 값을 명시적으로 넘겨서, 이미
    CURRENT_TIMESTAMP로 만들어진 기존 테이블이라도 새로 저장되는 행부터는
    바로 로컬 시각으로 찍히게 한다(스키마 마이그레이션 없이도 적용됨)."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
