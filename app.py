"""
auto_sms — 휴대폰과 연결(Phone Link) 앱을 조작해서
  1) 수신 문자를 자동으로 감지해 DB에 저장 (watch_daemon.py가 이 서버로 올려줌)
  2) 상용문구를 골라 원클릭으로 발송
하는 로컬 대시보드.

실행: python app.py  (기본 포트 8060)
watch_daemon.py와 phone_link.py는 pywinauto(Windows 전용)를 쓰므로 이 서버
자체는 아무 OS에서나 뜨지만, 실제 발송(/api/send)과 감시 데몬은 휴대폰
연결 앱이 설치된 윈도우 PC에서만 동작한다.
"""
from flask import Flask, jsonify, render_template, request

from db import get_db, init_db, make_dedup_key, now_local

app = Flask(__name__)
init_db()


# ── 대시보드 화면 ────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html")


def _build_threads(rows: list) -> list:
    """민원(수신 문자) 한 건에 답신(발신 문자)이 여러 개 이어질 수 있어서,
    평평한 메시지 목록을 "민원 + 그 이후 답신들" 스레드 단위로 묶는다.
    별도 컬럼/테이블로 연결을 저장하는 게 아니라, 같은 번호로 그 민원보다
    나중에 온 발신 문자를 답신으로 간주하는 시간 순서 규칙으로 그때그때
    계산한다 — 답신은 이제 화면의 "문자발송"이 항상 그 민원의 스레드
    안에서만 나가므로 이 규칙으로 충분하다.

    번호에 아직 수신 문자가 없는데 발신 문자가 먼저 있는 경우(과거 데이터 등)는
    그 발신 문자 자체를 스레드의 머리글로 두고 답신 컨트롤 없이 보여준다.

    limit으로 잘린 목록 범위 안에서만 묶으므로, 아주 오래된 민원의 답신이
    지금 화면에 안 보이는 범위에 있으면 별도 스레드로 갈라져 보일 수 있다 —
    "최근 메시지" 목록이 최근 활동을 보여주는 용도라 실용적으로 충분하다고
    보고, 정확성을 위해 전체 이력을 따로 조회하지는 않는다."""
    rows_asc = sorted(rows, key=lambda r: r["id"])
    open_thread_by_phone = {}
    threads = []
    for r in rows_asc:
        phone = r["phone_number"]
        if r["direction"] == "in":
            thread = {"complaint": r, "replies": []}
            threads.append(thread)
            open_thread_by_phone[phone] = thread
        else:
            thread = open_thread_by_phone.get(phone)
            if thread is None:
                thread = {"complaint": r, "replies": []}
                threads.append(thread)
                open_thread_by_phone[phone] = thread
            else:
                thread["replies"].append(r)
    threads.reverse()
    return threads


# ── 수신 메시지 ──────────────────────────────────────────
@app.route("/api/messages", methods=["GET"])
def api_list_messages():
    """최근 메시지 목록. phone 파라미터를 주면 그 번호와의 대화만 반환."""
    limit = request.args.get("limit", 100, type=int)
    phone = request.args.get("phone", "").strip()
    conn = get_db()
    if phone:
        rows = conn.execute(
            "SELECT * FROM messages WHERE phone_number=? ORDER BY id DESC LIMIT ?",
            (phone, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return jsonify({"threads": _build_threads([dict(r) for r in rows])})


@app.route("/api/messages", methods=["POST"])
def api_save_message():
    """watch_daemon.py가 새 수신 문자를 감지했을 때 호출하는 엔드포인트.
    같은 메시지가 여러 번 감지돼도(화면을 반복해서 훑으므로 흔함) dedup_key
    UNIQUE 제약으로 한 번만 저장된다 — INSERT OR IGNORE라 중복이어도 에러가
    아니라 조용히 무시되고, 그 여부를 inserted로 알려준다."""
    data = request.get_json(force=True, silent=True) or {}
    phone_number = (data.get("phone_number") or "").strip()
    body = (data.get("body") or "").strip()
    msg_time = (data.get("msg_time") or "").strip()
    contact_name = (data.get("contact_name") or "").strip()
    if not phone_number or not body:
        return jsonify({"error": "phone_number와 body는 필수입니다"}), 400

    dedup_key = make_dedup_key(phone_number, body, msg_time)
    conn = get_db()
    cur = conn.execute(
        "INSERT OR IGNORE INTO messages (phone_number, contact_name, body, direction, msg_time, dedup_key, created_at) "
        "VALUES (?,?,?,'in',?,?,?)",
        (phone_number, contact_name, body, msg_time, dedup_key, now_local()),
    )
    inserted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "inserted": inserted})


@app.route("/api/messages/<int:mid>/status", methods=["PATCH"])
def api_update_message_status(mid):
    data = request.get_json(force=True, silent=True) or {}
    status = (data.get("status") or "").strip()
    conn = get_db()
    conn.execute("UPDATE messages SET status=? WHERE id=?", (status, mid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/messages/<int:msg_id>", methods=["PUT"])
def api_update_message(msg_id):
    """민원 문자 목록에서 직원이 직접 채워 넣는 입력/접수번호를 저장한다.
    둘 다 자유 텍스트라 값 검증은 안 하고, 빈 문자열로 지우는 것도 그대로
    허용한다. 화면(dashboard.js)이 한 칸만 바뀌어도 그 행의 두 값을 항상
    같이 보내므로, 여기서도 두 컬럼을 한 번에 덮어쓴다 — 하나만 받으면
    나머지 한 칸이 빈 값으로 덮어써질 위험이 있어 일부러 이렇게 맞췄다.
    처리상태(status)는 이 라우트가 아니라 위의 PATCH .../status 전용
    엔드포인트로 따로 관리한다."""
    data = request.get_json(force=True, silent=True) or {}
    conn = get_db()
    if not conn.execute("SELECT 1 FROM messages WHERE id=?", (msg_id,)).fetchone():
        conn.close()
        return jsonify({"error": "메시지를 찾을 수 없습니다"}), 404
    conn.execute(
        "UPDATE messages SET manual_input=?, receipt_no=? WHERE id=?",
        (
            (data.get("manual_input") or "").strip(),
            (data.get("receipt_no") or "").strip(),
            msg_id,
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ── 상용문구 ─────────────────────────────────────────────
@app.route("/api/templates", methods=["GET"])
def api_list_templates():
    conn = get_db()
    rows = conn.execute("SELECT * FROM templates ORDER BY sort_no, id").fetchall()
    conn.close()
    return jsonify({"templates": [dict(r) for r in rows]})


@app.route("/api/templates", methods=["POST"])
def api_add_template():
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    if not title or not body:
        return jsonify({"error": "제목과 내용을 입력하세요"}), 400
    conn = get_db()
    conn.execute(
        "INSERT INTO templates (title, body, sort_no) VALUES (?,?,?)",
        (title, body, int(data.get("sort_no", 0))),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/templates/<int:tid>", methods=["PUT"])
def api_update_template(tid):
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    if not title or not body:
        return jsonify({"error": "제목과 내용을 입력하세요"}), 400
    conn = get_db()
    conn.execute(
        "UPDATE templates SET title=?, body=?, sort_no=? WHERE id=?",
        (title, body, int(data.get("sort_no", 0)), tid),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/templates/<int:tid>", methods=["DELETE"])
def api_delete_template(tid):
    conn = get_db()
    conn.execute("DELETE FROM templates WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ── 발송 ─────────────────────────────────────────────────
@app.route("/api/send", methods=["POST"])
def api_send():
    """대시보드의 '발송' 버튼 → 휴대폰과 연결 앱을 pywinauto로 조작해 실제
    문자를 보낸다. pywinauto는 윈도우 전용이라 여기서 지연 import한다 —
    그래야 리눅스/개발 환경에서도 서버 자체(메시지 목록, 상용문구 관리)는
    문제없이 뜨고, 실제 발송을 시도할 때만 이 라우트에서 에러가 난다."""
    data = request.get_json(force=True, silent=True) or {}
    phone_number = (data.get("phone_number") or "").strip()
    body = (data.get("body") or "").strip()
    if not phone_number or not body:
        return jsonify({"error": "수신번호와 문구를 입력하세요"}), 400

    try:
        import phone_link
    except Exception as e:
        return jsonify({"error": f"phone_link 모듈을 불러오지 못했습니다 (윈도우 전용 기능입니다): {e}"}), 500

    try:
        phone_link.send_message(phone_number, body)
    except Exception as e:
        return jsonify({"error": f"발송 실패: {e}"}), 502

    conn = get_db()
    # dedup_key는 워처가 같은 수신 문자를 중복 저장하지 않게 막는 용도라 발신
    # 기록에는 필요 없다 — NULL로 두면(SQLite는 NULL끼리 UNIQUE 충돌을 안 봄)
    # 같은 번호로 같은 문구를 여러 번 보내도 매번 정상적으로 기록된다.
    conn.execute(
        "INSERT INTO messages (phone_number, body, direction, dedup_key, created_at) VALUES (?,?,'out',NULL,?)",
        (phone_number, body, now_local()),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8060, debug=False)
