import requests

url = "https://www.konkuk.ac.kr/bbs/ee/407/artclList.do"

headers = {
    "User-Agent": (
        # 예전 Netscape/Mozilla 계열 브라우저처럼 보이기 위한 관습적 접두어
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " 
        #Chrome과 Safari가 공통으로 영향을 받은 렌더링 엔진 계열 이름
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.konkuk.ac.kr/",
}

response = requests.get(url, headers=headers, timeout=10)
response.encoding = "utf-8"

print(response.status_code)
print(response.text[:1000])