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
import threading
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

    thread_id가 찍혀 있는 메시지들은 그 값이 같은 것끼리 무조건 한
    스레드로 묶는다 — 체크박스로 수동 병합된 것(api_merge_threads() 참고)
    뿐 아니라, 화면의 "문자발송"으로 보낸 답신도 그 답신이 어느 민원 밑
    send-box에서 나갔는지(complaint_id, api_send() 참고)에 따라 그 민원의
    thread_id로 명시적으로 묶인다. 같은 번호로 서로 다른 민원이 따로 와
    있을 수 있어서, 번호만 보고 "그 민원보다 나중에 온 발신 문자는 다
    답신"으로 넘겨짚으면 오래된 민원에 대한 답신이 그 번호의 최신 민원
    스레드로 잘못 붙어버린다 — 그래서 thread_id 없이 들어오는 발신
    문자(예: 업무외 자동발송, watch_daemon이 감지한 옛 데이터)에 한해서만
    아래의 시간 순서 규칙(같은 번호로 그 민원보다 나중에 온 발신 문자를
    답신으로 간주)으로 보조적으로 묶는다.

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
AUTO_REPLY_QUIET_MINUTES = 1


def _is_business_hours(now: datetime = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:  # 5=토요일, 6=일요일
        return False
    return BUSINESS_START_HOUR <= now.hour < BUSINESS_END_HOUR


def _dispatch_auto_reply(phone_number: str):
    """_maybe_send_auto_reply()를 별도 스레드에서 실행한다.

    phone_link.send_message()는 창을 찾고 열고 타이핑하고 보내기 버튼을
    누르는 여러 단계를 거치는 실제 UI 자동화라 몇 초에서 길게는 그 이상
    걸릴 수 있다. 이 서버(app.run())는 threaded=False라 요청을 한 번에
    하나씩만 처리하는데, 이 호출을 요청 처리 스레드에서 그대로 기다리면
    — (1) watch_daemon.py 쪽 요청이 10초 타임아웃에 걸려 "전송 실패"로
    잘못 보이고(실제로는 수신 문자 저장 자체는 이미 끝난 뒤라 성공한
    경우가 많음), (2) 더 심각하게는 그 사이 들어오는 다른 요청들(새 수신
    문자 저장, 대시보드 조회 등)이 전부 그 뒤에 밀려서, 자동발송이 오래
    걸리거나 멈춰버리면 그동안 새 문자가 실제로 DB에 저장되지 않는
    것처럼 보이는 문제로 이어진다. 그래서 자동발송은 응답을 기다리지
    않고 별도 스레드로 넘겨서, 수신 문자 저장 응답은 항상 즉시 돌아가고
    서버도 그 사이 다른 요청을 계속 받을 수 있게 한다.

    ⚠ 이 스레드는 Flask 요청 스레드가 아니라 새로 뜨는 스레드라, 그
    안에서 pywinauto(UI Automation)를 처음 쓰는 거면 윈도우에서 그
    스레드용으로 COM을 따로 초기화해줘야 한다(스레드마다 필요, 메인
    스레드에서 됐다고 다른 스레드까지 적용되는 게 아님). pythoncom도
    윈도우 전용이라 phone_link처럼 지연 import하고, 실패하면(리눅스 등)
    그냥 건너뛴다."""
    def run():
        com_initialized = False
        try:
            import pythoncom
            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
            com_initialized = True
        except Exception:
            pass
        try:
            _maybe_send_auto_reply(phone_number)
        except Exception as e:
            print(f"[업무외 자동발송] 예상 못한 오류 ({phone_number}): {e!r}")
        finally:
            if com_initialized:
                import pythoncom
                pythoncom.CoUninitialize()

    threading.Thread(target=run, daemon=True).start()


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

    # phone_link.send_message()는 창을 열고 타이핑하고 보내기까지 여러 단계를
    # 거치는 실제 UI 자동화라 몇 초씩 걸릴 수 있고, 그 사이 use_reloader가
    # git pull로 바뀐 파일을 감지해 프로세스를 재시작하는 것과 타이밍이
    # 겹치면 발송 직후 코드가 아예 실행되다 만 채로 끊길 수 있다. 그래서
    # "문자는 실제로 나갔는데 기록만 안 남는" 사고를 최대한 줄이려고, DB
    # 기록을 발송 "전에" 먼저 남겨두고(발송에 실패한 경우에만 되돌린다) —
    # 반대 순서(발송 후 기록)로 하면 발송은 됐는데 기록이 아예 안 남는
    # 쪽으로 실패하기 쉽고, 그 경우는 원인도 알기 어렵다.
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO messages (phone_number, body, direction, dedup_key, created_at, auto_sent) VALUES (?,?,'out',NULL,?,1)",
        (phone_number, body, now_local()),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        import phone_link
        phone_link.send_message(phone_number, body)
    except Exception as e:
        print(f"[업무외 자동발송] 발송 실패, 기록도 되돌립니다 ({phone_number}): {e!r}")
        conn = get_db()
        conn.execute("DELETE FROM messages WHERE id=?", (row_id,))
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

    conn = get_db()
    # 알림 패널 파싱(phone_link.py)이 우리가 보낸 답신을 수신 문자로 잘못
    # 잡아내는 경우에 대한 안전망 — 알림 카드 안에서 "나"가 보낸 구간을
    # UI 구조만으로 완벽하게 구분하기 어려워서(실제로 그 판단 로직이
    # 오히려 진짜 수신 문자를 놓치는 사고로 이어진 적도 있음), 여기서는
    # 같은 번호로 우리가 최근에 정확히 같은 문구를 보낸 적이 있는지를
    # 서버 쪽 실제 발신 기록으로 한 번 더 확인한다 — 있으면 우리 답신이
    # 알림에 다시 잡힌 것으로 보고 수신 문자로 저장하지 않는다. 기간을
    # 하루로 넉넉히 잡은 이유는 알림 카드가 하루 넘게 안 지워지고 화면에
    # 그대로 남아있는 경우도 실제로 있기 때문이다.
    self_echo = conn.execute(
        "SELECT 1 FROM messages WHERE phone_number=? AND direction='out' AND body=? "
        "AND created_at >= datetime('now','localtime','-1 day') LIMIT 1",
        (phone_number, body),
    ).fetchone()
    if self_echo:
        conn.close()
        return jsonify({"ok": True, "inserted": False, "skipped_self_echo": True})

    dedup_key = make_dedup_key(phone_number, body, msg_time)
    cur = conn.execute(
        "INSERT OR IGNORE INTO messages (phone_number, contact_name, body, direction, msg_time, dedup_key, created_at) "
        "VALUES (?,?,?,'in',?,?,?)",
        (phone_number, contact_name, body, msg_time, dedup_key, now_local()),
    )
    inserted = cur.rowcount > 0
    conn.commit()
    conn.close()
    if inserted:
        # 별도 스레드로 넘겨서 자동발송(느릴 수 있는 UI 자동화)이 끝나길
        # 기다리지 않고 바로 응답한다 — 이유는 _dispatch_auto_reply() 설명
        # 참고. 스레드 안에서 나는 예외는 거기서 이미 잡아서 로그만 남기므로
        # 여기서 또 감쌀 필요는 없다.
        _dispatch_auto_reply(phone_number)
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
    complaint_id = data.get("complaint_id")
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
    # 같은 번호로 서로 다른 민원이 따로 들어와 있을 수 있다 — thread_id 없이
    # phone_number만으로 저장하면 _build_threads()가 그 번호의 "가장 최근"
    # 수신 스레드에 무조건 붙여버려서, 예전 민원 화면에서 답신을 보내도
    # 최신 민원 스레드로 잘못 들어가 버린다. 그래서 화면이 어떤 민원(스레드)
    # 밑에서 보낸 답신인지(complaint_id)를 같이 보내주면, 그 스레드에
    # 명시적으로 묶는다 — 그 민원이 아직 한 번도 병합된 적 없어 thread_id가
    # 비어 있으면(api_merge_threads와 같은 규칙으로) 자기 자신의 id를
    # thread_id로 삼아 스스로를 앵커로 만든다.
    thread_id = None
    if complaint_id:
        row = conn.execute("SELECT thread_id FROM messages WHERE id=?", (complaint_id,)).fetchone()
        if row:
            thread_id = row["thread_id"] or complaint_id
            if row["thread_id"] is None:
                conn.execute("UPDATE messages SET thread_id=? WHERE id=?", (thread_id, complaint_id))
    # dedup_key는 워처가 같은 수신 문자를 중복 저장하지 않게 막는 용도라 발신
    # 기록에는 필요 없다 — NULL로 두면(SQLite는 NULL끼리 UNIQUE 충돌을 안 봄)
    # 같은 번호로 같은 문구를 여러 번 보내도 매번 정상적으로 기록된다.
    conn.execute(
        "INSERT INTO messages (phone_number, body, direction, dedup_key, created_at, thread_id) VALUES (?,?,'out',NULL,?,?)",
        (phone_number, body, now_local(), thread_id),
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
    # threaded=True: 기본(False)이면 요청을 한 번에 하나씩만 처리해서, 느린
    # 요청 하나가 그 뒤의 다른 요청(새 수신 문자 저장, 대시보드 조회 등)을
    # 전부 막아버린다 — 자동발송은 별도 스레드로 넘겨서 이미 웬만큼
    # 피했지만(_dispatch_auto_reply() 참고), 여러 요청이 동시에 몰리는
    # 상황 자체를 근본적으로 막기 위해 이중으로 켜둔다.
    app.run(host="0.0.0.0", port=8060, debug=False, use_reloader=True, threaded=True)
