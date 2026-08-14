# -*- coding: utf-8 -*-
"""
휴대폰 연결 앱을 상시 감시하다가 새 문자를 발견하면 auto_sms 서버(app.py)에
저장 요청을 보내는 데몬. app.py와 별도 프로세스로 계속 띄워둔다.

사용법:
    python app.py                         (다른 터미널/서비스로 먼저 띄워둠)
    python watch_daemon.py                (기본: http://127.0.0.1:5060, 10초 간격)
    python watch_daemon.py --server http://127.0.0.1:5060 --interval 15
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
    parser.add_argument("--server", default="http://127.0.0.1:5060")
    parser.add_argument("--interval", type=int, default=10, help="감시 주기(초)")
    args = parser.parse_args()

    phone_link.watch_new_messages(make_reporter(args.server), poll_interval=args.interval)
