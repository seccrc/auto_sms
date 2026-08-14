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
            created_at    TEXT DEFAULT (datetime('now', 'localtime'))
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
    """)
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
