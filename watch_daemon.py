# -*- coding: utf-8 -*-
"""
휴대폰과 연결 앱을 상시 감시하다가 새 문자를 발견하면 auto_sms 서버(app.py)에
저장 요청을 보내는 데몬. app.py와 별도 프로세스로 계속 띄워둔다.

기본 감시 소스는 "알림" 패널이다 — 행정망처럼 PC에 Wi-Fi를 못 붙이는
환경에서도 문자 알림은 블루투스만으로 오는 걸 확인했다. 대화 목록
(CVSListView) 기반 감시는 본문 동기화에 Wi-Fi가 필요해서 그 상황에서는
새 메시지를 못 읽는다 — Wi-Fi가 되는 환경이면 --source messages로 바꿀 수
있다(다만 알림 쪽보다 본문이 잘리지 않고 완전하다는 장점이 있음).

사용법:
    python app.py                         (다른 터미널/서비스로 먼저 띄워둠)
    python watch_daemon.py                (기본: 알림 패널 감시, http://127.0.0.1:8060, 10초 간격)
    python watch_daemon.py --source messages --server http://127.0.0.1:8060 --interval 15
"""
import argparse

import requests

import phone_link


def make_reporter(server: str):
    def report(phone_number, contact_name, body, msg_time):
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
                print(f"[저장] {phone_number}: {body[:30]}")
        except Exception as e:
            print(f"[경고] 서버로 전송 실패 ({phone_number}): {e!r}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8060")
    parser.add_argument("--interval", type=int, default=10, help="감시 주기(초)")
    parser.add_argument(
        "--source", choices=["notifications", "messages"], default="notifications",
        help="notifications=알림 패널(Wi-Fi 불필요, 기본) / messages=대화 목록(Wi-Fi 필요, 본문 안 잘림)"
    )
    args = parser.parse_args()

    reporter = make_reporter(args.server)
    if args.source == "notifications":
        phone_link.watch_notifications(reporter, poll_interval=args.interval)
    else:
        phone_link.watch_new_messages(reporter, poll_interval=args.interval)
