# -*- coding: utf-8 -*-
"""
휴대폰과 연결 앱을 상시 감시하다가 새 문자를 발견하면 auto_sms 서버(app.py)에
저장 요청을 보내는 데몬. app.py와 별도 프로세스로 계속 띄워둔다.

기본 감시 소스는 "알림" 패널이다 — 행정망처럼 PC에 Wi-Fi를 못 붙이는
환경에서도 문자 알림은 블루투스만으로 오는 걸 확인했다. 대화 목록
(CVSListView) 기반 감시는 본문 동기화에 Wi-Fi가 필요해서 그 상황에서는
새 메시지를 못 읽는다 — Wi-Fi가 되는 환경이면 --source messages로 바꿀 수
있다(다만 알림 쪽보다 본문이 잘리지 않고 완전하다는 장점이 있음).

같은 번호에서 --merge-window초 안에 연달아 문자가 오면 한 건으로 합쳐서
저장한다 — 민원인이 내용이 길어서 문자를 2~3통으로 나눠 보내는 경우를
한 건의 문의로 묶어주기 위함. 이 시간 간격이 지나야 실제로 저장되므로,
그만큼 대시보드 반영이 늦어진다는 점은 감안해야 한다(자세한 설명은
make_reporter() 참고).

사용법:
    python app.py                         (다른 터미널/서비스로 먼저 띄워둠)
    python watch_daemon.py                (기본: 알림 패널 감시, http://127.0.0.1:8060, 10초 간격)
    python watch_daemon.py --source messages --server http://127.0.0.1:8060 --interval 15
    python watch_daemon.py --merge-window 20   (나눠 보낸 문자를 더 넉넉하게 기다렸다 합침)
"""
import argparse
import threading

import requests

import phone_link


def make_reporter(server: str, merge_window: float = 8.0):
    """새 문자 한 줄을 받을 때마다 바로 서버에 올리지 않고, 같은 번호로 온
    문자를 merge_window초 동안 모았다가 한 번에 합쳐서 저장한다.

    민원인이 문자 하나로 다 못 써서 "..." 식으로 2~3통에 나눠 보내는 경우,
    그 사이 간격이 merge_window초보다 짧으면 자연스럽게 한 건으로 합쳐진다
    (본문은 줄바꿈으로 이어붙임). 반대로 간격이 그보다 길면 별개 문의로
    보고 따로 저장한다.

    다만 이건 "그 사이에 새 줄이 더 안 왔다"는 것만으로 판단하는 추정이라
    완벽하지 않다 — 우연히 같은 사람이 merge_window 안에 실제로 다른
    용건의 문자를 연달아 보내면 그것도 하나로 합쳐진다. 그게 걸리면
    --merge-window를 줄이고, 반대로 나눠 보낸 문자가 자주 따로따로
    저장되면 늘리면 된다."""
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8060")
    parser.add_argument("--interval", type=int, default=10, help="감시 주기(초)")
    parser.add_argument(
        "--source", choices=["notifications", "messages"], default="notifications",
        help="notifications=알림 패널(Wi-Fi 불필요, 기본) / messages=대화 목록(Wi-Fi 필요, 본문 안 잘림)"
    )
    parser.add_argument(
        "--merge-window", type=float, default=8.0,
        help="같은 번호에서 이 초 안에 연달아 오는 문자는 한 건으로 합쳐서 저장 (기본 8초, 0이면 합치지 않음)"
    )
    args = parser.parse_args()

    reporter = make_reporter(args.server, merge_window=args.merge_window)
    try:
        if args.source == "notifications":
            phone_link.watch_notifications(reporter, poll_interval=args.interval)
        else:
            phone_link.watch_new_messages(reporter, poll_interval=args.interval)
    except KeyboardInterrupt:
        print("\n[종료] 합치는 중이던 메시지를 마저 저장합니다...")
        reporter.flush_all()
        raise
