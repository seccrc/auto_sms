# -*- coding: utf-8 -*-
"""
휴대폰과 연결 앱을 상시 감시하다가 새 문자를 발견하면 auto_sms 서버(app.py)에
저장 요청을 보내는 데몬. app.py와 별도 프로세스로 계속 띄워둔다.

기본 감시 소스는 "알림" 패널이다 — 행정망처럼 PC에 Wi-Fi를 못 붙이는
환경에서도 문자 알림은 블루투스만으로 오는 걸 확인했다. 대화 목록
(CVSListView) 기반 감시는 본문 동기화에 Wi-Fi가 필요해서 그 상황에서는
새 메시지를 못 읽는다 — Wi-Fi가 되는 환경이면 --source messages로 바꿀 수
있다(다만 알림 쪽보다 본문이 잘리지 않고 완전하다는 장점이 있음).

--merge-window를 0보다 크게 주면, 같은 번호에서 그 초 안에 연달아 오는
문자를 한 건으로 합쳐서 저장한다 — 민원인이 내용이 길어서 문자를 2~3통으로
나눠 보내는 경우를 한 건의 문의로 묶어주기 위한 옵션. 다만 그만큼 대시보드
반영이 늦어지고, 우연히 다른 용건을 연달아 보내면 잘못 합쳐질 수도 있어서
기본값은 0(합치지 않고 감지 즉시 저장)이다. 긴급한 신고(로드킬 등)일수록
지연 없이 바로 보이는 게 중요하다고 판단해 기본은 꺼둠 — 필요할 때만 켜서
쓰면 된다(자세한 설명은 make_reporter() 참고).

사용법:
    python app.py                         (다른 터미널/서비스로 먼저 띄워둠)
    python watch_daemon.py                (기본: 알림 패널 감시, http://127.0.0.1:8060, 5초 간격, 병합 없음)
    python watch_daemon.py --source messages --server http://127.0.0.1:8060 --interval 15
    python watch_daemon.py --merge-window 20   (나눠 보낸 문자를 15~20초 정도 기다렸다 합침)
"""
import argparse
import threading

import requests

import phone_link


def make_reporter(server: str, merge_window: float = 0.0):
    """새 문자 한 줄을 받으면 기본적으로(merge_window=0) 감지 즉시 서버에
    저장한다.

    merge_window를 0보다 크게 주면, 같은 번호로 온 문자를 그 초만큼 모았다가
    한 번에 합쳐서 저장하는 방식으로 바뀐다 — 민원인이 문자 하나로 다 못
    써서 "..." 식으로 2~3통에 나눠 보내는 경우, 그 사이 간격이 merge_window
    초보다 짧으면 자연스럽게 한 건으로 합쳐진다(본문은 줄바꿈으로 이어붙임).
    반대로 간격이 그보다 길면 별개 문의로 보고 따로 저장한다.

    다만 이건 "그 사이에 새 줄이 더 안 왔다"는 것만으로 판단하는 추정이라
    완벽하지 않다 — 우연히 같은 사람이 merge_window 안에 실제로 다른
    용건의 문자를 연달아 보내면 그것도 하나로 합쳐진다. 그리고 병합
    자체가 그 시간만큼 대시보드 반영을 늦춘다. 그래서 기본값은 0(합치지
    않음)이고, 나눠 보낸 문자를 자주 놓친다 싶을 때만 켜서 쓰면 된다."""
    pending = {}  # phone -> {"lines": [...], "contact_name": str, "msg_time": str, "timer": Timer}
    lock = threading.Lock()

    def send(phone_number, contact_name, body, msg_time):
        try:
            r = requests.post(
                f"{server}/api/messages",
                json={
                    "phone_number": phone_number,
                    "contact_name": contact_name,
                    "body": body,
                    "msg_time": msg_time,
                },
                timeout=10,
            )
            if r.ok and r.json().get("inserted"):
                preview = body[:30].replace("\n", " / ")
                print(f"[저장] {phone_number}: {preview}")
        except Exception as e:
            print(f"[경고] 서버로 전송 실패 ({phone_number}): {e!r}")

    def flush(phone_number):
        with lock:
            entry = pending.pop(phone_number, None)
        if entry:
            send(phone_number, entry["contact_name"], "\n".join(entry["lines"]), entry["msg_time"])

    def report(phone_number, contact_name, body, msg_time):
        if merge_window <= 0:
            # 병합을 아예 켜지 않은 기본 상태 - 타이머를 거치지 않고 즉시
            # 보낸다. 0초 타이머로 처리하면 report()가 연달아 두 번 불릴 때
            # 두 번째 호출이 첫 번째 타이머를 취소해버려(아직 안 실행됐으므로)
            # 오히려 합쳐지는 경쟁 상태가 생겨서, 이 경로는 별도로 뺐다.
            send(phone_number, contact_name, body, msg_time)
            return
        with lock:
            entry = pending.get(phone_number)
            if entry is None:
                entry = {"lines": [], "contact_name": contact_name, "msg_time": msg_time, "timer": None}
                pending[phone_number] = entry
            entry["lines"].append(body)
            if contact_name:
                entry["contact_name"] = contact_name
            if entry["timer"]:
                entry["timer"].cancel()
            timer = threading.Timer(merge_window, flush, args=(phone_number,))
            timer.daemon = True
            entry["timer"] = timer
            timer.start()

    def flush_all():
        """종료 직전에 merge_window가 아직 안 지나 대기 중인 메시지를
        마저 저장하기 위한 함수. main에서 Ctrl+C 시 호출한다."""
        with lock:
            phones = list(pending.keys())
        for p in phones:
            flush(p)

    report.flush_all = flush_all
    return report


def _load_recent_seen(server: str, limit: int = 300) -> dict:
    """서버(app.py)에 이미 저장된 최근 수신 메시지를 {번호: {본문 줄, ...}}
    형태로 불러온다.

    watch_daemon.py를 껐다 켜면 phone_link.watch_notifications()/
    watch_new_messages()의 "이미 처리한 내용" 기억이 메모리라서
    초기화되는데, 그 시점에 알림 카드나 대화 목록에 예전 내용이 그대로
    남아있으면 이미 저장된 걸 "새 것"으로 착각해서 서버로 또 올리는
    문제가 실제로 있었다. 시작하기 전에 서버가 이미 아는 내용을 미리
    불러와서 phone_link 쪽 중복 방지 상태를 채워두면, 알림/대화 목록 자체는
    안 건드리면서도 재시작으로 인한 중복 저장을 막을 수 있다.

    ⚠ 저장된 body를 줄 단위로 쪼개서 넣는다 — --merge-window를 켜서 여러
    줄이 "A\\nB"처럼 하나로 합쳐져 저장된 경우, phone_link 쪽에서는 여전히
    알림 카드의 "A", "B" 개별 줄과 비교하기 때문에, 합쳐진 문자열을
    그대로 넣으면 개별 줄과 하나도 안 맞아서 재시작 시 다시 중복
    저장되는 문제가 있었다. 병합을 안 쓰는 경우(기본값)엔 한 줄짜리
    body를 쪼개봐야 자기 자신 하나만 나오므로 동작에 차이가 없다.

    서버 연결에 실패하면 빈 상태로 시작한다 — 이 함수가 실패한다고 감시
    자체를 못 하게 막을 이유는 없고, 최악의 경우도 예전과 같은(중복 가능)
    동작으로 돌아가는 것뿐이다."""
    seen = {}
    try:
        r = requests.get(f"{server}/api/messages", params={"limit": limit}, timeout=10)
        r.raise_for_status()
        # /api/messages는 평평한 목록이 아니라 스레드({"complaint": ..,
        # "replies": [..]}) 단위로 내려온다 — 민원(complaint)과 그 안에 섞여
        # 들어갈 수 있는 수신 문자(답신 사이에 다시 온 후속 민원 등)를 모두
        # 훑어야 "이미 저장된 수신 문자"를 빠짐없이 기억한다.
        for t in r.json().get("threads", []):
            candidates = [t.get("complaint")] + (t.get("replies") or [])
            for m in candidates:
                if not m or m.get("direction") != "in":
                    continue
                already_seen = seen.setdefault(m["phone_number"], set())
                for line in (m["body"] or "").split("\n"):
                    if line:
                        already_seen.add(line)
    except Exception as e:
        print(f"[경고] 기존 메시지를 불러오지 못해 중복 방지 없이 시작합니다: {e!r}")
    return seen


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8060")
    parser.add_argument("--interval", type=int, default=5, help="감시 주기(초)")
    parser.add_argument(
        "--source", choices=["notifications", "messages"], default="notifications",
        help="notifications=알림 패널(Wi-Fi 불필요, 기본) / messages=대화 목록(Wi-Fi 필요, 본문 안 잘림)"
    )
    parser.add_argument(
        "--merge-window", type=float, default=0.0,
        help="같은 번호에서 이 초 안에 연달아 오는 문자는 한 건으로 합쳐서 저장 (기본 0=합치지 않고 즉시 저장)"
    )
    parser.add_argument(
        "--hide", action="store_true",
        help="첫 폴링을 마친 직후 휴대폰과 연결 창을 자동으로 최소화합니다 "
             "(처음부터 최소화된 채로 시작하면 목록이 계속 안 읽히는 걸 확인해서, "
             "시작 시점엔 창을 보이게 뒀다가 한 번 읽고 난 뒤에 숨김)"
    )
    args = parser.parse_args()

    reporter = make_reporter(args.server, merge_window=args.merge_window)
    initial_seen = _load_recent_seen(args.server)
    try:
        if args.source == "notifications":
            phone_link.watch_notifications(
                reporter, poll_interval=args.interval, hide_after_start=args.hide,
                seen_lines_by_sender=initial_seen,
            )
        else:
            phone_link.watch_new_messages(
                reporter, poll_interval=args.interval, hide_after_start=args.hide,
                seen_bodies_by_phone=initial_seen,
            )
    except KeyboardInterrupt:
        print("\n[종료] 합치는 중이던 메시지를 마저 저장합니다...")
        reporter.flush_all()
        raise
