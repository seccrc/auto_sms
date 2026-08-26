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
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from db import get_db, get_setting, init_db, make_dedup_key, now_local, set_setting

app = Flask(__name__)
# git pull로 dashboard.html이 바뀌어도 서버 재시작 없이 다음 요청부터 바로
# 반영되게 한다 (기본은 템플릿을 한 번 읽으면 계속 캐시해서 쓴다).
app.config["TEMPLATES_AUTO_RELOAD"] = True
init_db()


# ── 대시보드 화면 ────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html")


def _build_threads(rows: list) -> list:
    """민원(수신 문자) 한 건에 답신(발신 문자)이 여러 개 이어질 수 있어서,
    평평한 메시지 목록을 "민원 + 그 이후 답신들" 스레드 단위로 묶는다.

    thread_id가 찍혀 있는 메시지들(체크박스로 수동 병합된 것 — 아래
    api_merge_threads() 참고)은 그 값이 같은 것끼리 무조건 한 스레드로
    묶는다. 그게 아닌 메시지는 기존과 같이, 같은 번호로 그 민원보다
    나중에 온 발신 문자를 답신으로 간주하는 시간 순서 규칙으로 그때그때
    자동으로 묶는다 — 답신은 화면의 "문자발송"이 항상 그 민원의 스레드
    안에서만 나가므로 이 규칙으로 충분하다.

    번호에 아직 수신 문자가 없는데 발신 문자가 먼저 있는 경우(과거 데이터 등)는
    그 발신 문자 자체를 스레드의 머리글로 두고 답신 컨트롤 없이 보여준다.

    limit으로 잘린 목록 범위 안에서만 묶으므로, 아주 오래된 민원의 답신이
    지금 화면에 안 보이는 범위에 있으면 별도 스레드로 갈라져 보일 수 있다 —
    "최근 메시지" 목록이 최근 활동을 보여주는 용도라 실용적으로 충분하다고
    보고, 정확성을 위해 전체 이력을 따로 조회하지는 않는다."""
    rows_asc = sorted(rows, key=lambda r: r["id"])
    threads_by_manual_id = {}
    open_thread_by_phone = {}
    threads = []
    for r in rows_asc:
        manual_tid = r.get("thread_id")
        if manual_tid:
            thread = threads_by_manual_id.get(manual_tid)
            if thread is None:
                thread = {"complaint": r, "replies": []}
                threads_by_manual_id[manual_tid] = thread
                threads.append(thread)
            else:
                thread["replies"].append(r)
            continue
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


# 업무외 자동발송이 "업무시간"으로 볼 범위 — 평일 09:00~18:00. 필요하면 이
# 상수만 바꾸면 된다(화면에는 아직 별도 설정 UI가 없음).
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 18

# 나눠 보낸 문자처럼 같은 번호에서 짧은 시간 안에 여러 통이 연달아 올 때,
# 매 통마다 자동발송이 또 나가면 스팸처럼 느껴진다 — 그 번호로 이 시간(분)
# 안에 이미 발신 문자가 나갔으면 자동발송을 건너뛴다.
AUTO_REPLY_QUIET_MINUTES = 5


def _is_business_hours(now: datetime = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:  # 5=토요일, 6=일요일
        return False
    return BUSINESS_START_HOUR <= now.hour < BUSINESS_END_HOUR


def _maybe_send_auto_reply(phone_number: str):
    """업무외 시간에 새 민원이 들어왔고 "업무외 자동발송"이 켜져 있으면,
    화면에서 골라둔 상용문구를 그 번호로 자동 발송한다. 업무시간 안이면
    직원이 직접 확인/발송하는 게 기본이라 아무것도 하지 않는다."""
    if _is_business_hours():
        return

    conn = get_db()
    try:
        if get_setting("auto_reply_enabled", "0") != "1":
            return
        template_id = get_setting("auto_reply_template_id", "")
        if not template_id:
            return
        template = conn.execute(
            "SELECT body FROM templates WHERE id=?", (template_id,)
        ).fetchone()
        if not template:
            return
        recent_out = conn.execute(
            "SELECT 1 FROM messages WHERE phone_number=? AND direction='out' "
            f"AND created_at >= datetime('now','localtime','-{AUTO_REPLY_QUIET_MINUTES} minutes') LIMIT 1",
            (phone_number,),
        ).fetchone()
        if recent_out:
            return
        body = template["body"]
    finally:
        conn.close()

    try:
        import phone_link
        phone_link.send_message(phone_number, body)
    except Exception as e:
        print(f"[업무외 자동발송] 실패 ({phone_number}): {e!r}")
        return

    conn = get_db()
    conn.execute(
        "INSERT INTO messages (phone_number, body, direction, dedup_key, created_at, auto_sent) VALUES (?,?,'out',NULL,?,1)",
        (phone_number, body, now_local()),
    )
    conn.commit()
    conn.close()


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
    if inserted:
        _maybe_send_auto_reply(phone_number)
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


@app.route("/api/threads/merge", methods=["POST"])
def api_merge_threads():
    """같은 민원인이 시간차를 두고 다시 보내서 스레드가 갈라진 경우를 위한
    기능 — 화면에서 체크박스로 고른 여러 스레드(각각의 민원 id로 식별)를
    한 스레드로 합친다. 각 스레드에 이미 딸려 있는 답신들까지 포함해서
    관련된 모든 메시지에 같은 thread_id를 매기면, 다음 조회부터
    _build_threads()가 그 값으로 하나로 묶어서 보여준다.

    thread_id는 합쳐지는 메시지들 중 가장 작은(가장 오래된) id를 그대로
    쓴다 — 이미 한 번 병합된 스레드를 다른 스레드와 또 합치는 경우에도
    _build_threads()가 기존 thread_id를 우선하므로 자동으로 같이 딸려온다."""
    data = request.get_json(force=True, silent=True) or {}
    complaint_ids = data.get("complaint_ids") or []
    if not isinstance(complaint_ids, list) or len(complaint_ids) < 2:
        return jsonify({"error": "병합하려면 스레드를 2개 이상 선택하세요"}), 400

    conn = get_db()
    rows = conn.execute("SELECT * FROM messages ORDER BY id").fetchall()
    threads = _build_threads([dict(r) for r in rows])

    target_ids = set()
    for t in threads:
        if t["complaint"]["id"] in complaint_ids:
            target_ids.add(t["complaint"]["id"])
            target_ids.update(rp["id"] for rp in t["replies"])
    if not target_ids:
        conn.close()
        return jsonify({"error": "선택한 스레드를 찾을 수 없습니다"}), 404

    new_thread_id = min(target_ids)
    conn.executemany(
        "UPDATE messages SET thread_id=? WHERE id=?",
        [(new_thread_id, mid) for mid in target_ids],
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "thread_id": new_thread_id})


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


# ── 업무외 자동발송 설정 ────────────────────────────────────
@app.route("/api/settings/auto_reply", methods=["GET"])
def api_get_auto_reply_settings():
    template_id = get_setting("auto_reply_template_id", "")
    return jsonify({
        "enabled": get_setting("auto_reply_enabled", "0") == "1",
        "template_id": int(template_id) if template_id else None,
        "business_hours_now": _is_business_hours(),
    })


@app.route("/api/settings/auto_reply", methods=["PUT"])
def api_update_auto_reply_settings():
    data = request.get_json(force=True, silent=True) or {}
    set_setting("auto_reply_enabled", "1" if data.get("enabled") else "0")
    template_id = data.get("template_id")
    set_setting("auto_reply_template_id", str(template_id) if template_id else "")
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
    # use_reloader=True: app.py/db.py를 git pull로 덮어써도 파일 변경을 감지해
    # 프로세스를 알아서 재시작한다(매번 손으로 껐다 켤 필요 없음). debug=True를
    # 켜서 얻는 부작용(인터랙티브 디버거)은 host="0.0.0.0"으로 네트워크에
    # 열려있는 이 서버에서는 원격 코드실행 위험이라 debug는 그대로 꺼둔 채
    # use_reloader만 켠다.
    app.run(host="0.0.0.0", port=8060, debug=False, use_reloader=True)
