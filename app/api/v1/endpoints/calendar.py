# 캘린더 관련 API 모음
# calender.py
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, logger
from pydantic import BaseModel
import pytz
from app.api.v1.endpoints import login, users, google, calendar 
from app.api.deps import get_current_user
from app.db.dynamo import get_weekly_activity_data, put_calendar_list, store_calendar_events
from app.models.user import User
import httpx
import json
import logging
import traceback

# calendar.py 전용 로거 설정
calendar_logger = logging.getLogger('calendar')
calendar_logger.setLevel(logging.INFO)

# 파일 핸들러 추가
file_handler = logging.FileHandler('calendar.log')
file_handler.setLevel(logging.INFO)

# 스트림 핸들러 추가 
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)

# 포맷터 설정 - calendar.py용 특별 포맷
formatter = logging.Formatter('[캘린더 API] %(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

calendar_logger.addHandler(file_handler)
calendar_logger.addHandler(stream_handler)

# API 라우터 설정

router = APIRouter()

async def refresh_google_token(refresh_token: str):
   calendar_logger.info("구글 토큰 갱신 프로세스 시작")
   
   try:
       # client secrets 파일 읽기
       calendar_logger.info("클라이언트 설정 파일 읽기 시작")
       with open("client_secret_639048076528-0mqbo91cf5t0fq5604u0tblqnaka8thp.apps.googleusercontent.com.json", "r") as f:
           client_config = json.load(f)["web"]
       calendar_logger.info("클라이언트 설정 파일 읽기 완료")

       # 요청 데이터 준비
       token_data = {
           "client_id": client_config["client_id"],
           "client_secret": client_config["client_secret"],
           "refresh_token": refresh_token,
           "grant_type": "refresh_token"
       }
       calendar_logger.info("토큰 갱신 요청 데이터 준비 완료")

       async with httpx.AsyncClient() as client:
           calendar_logger.info("구글 토큰 갱신 요청 시작")
           response = await client.post("https://oauth2.googleapis.com/token", data=token_data)
           response.raise_for_status()
           
           token_info = response.json()
           calendar_logger.info("구글 토큰 갱신 응답 수신 완료")
           
           if "access_token" not in token_info:
               calendar_logger.error("응답에 access_token이 없음")
               raise HTTPException(
                   status_code=400,
                   detail="액세스 토큰 갱신 실패"
               )
               
           calendar_logger.info("새로운 액세스 토큰 발급 성공")
           return token_info["access_token"]
           
   except httpx.HTTPError as e:
       calendar_logger.error(f"구글 토큰 갱신 중 HTTP 에러 발생: {str(e)}")
       calendar_logger.error(f"상세 에러: {traceback.format_exc()}")
       raise HTTPException(
           status_code=500,
           detail="구글 액세스 토큰 갱신 실패"
       )
   except Exception as e:
       calendar_logger.error(f"토큰 갱신 중 예상치 못한 에러 발생: {str(e)}")
       calendar_logger.error(f"상세 에러: {traceback.format_exc()}")
       raise HTTPException(
           status_code=500,
           detail="토큰 갱신 중 내부 서버 오류 발생"
       )

@router.post("/sync-calendar")
async def sync_calendar(current_user: User = Depends(get_current_user)):
   calendar_logger.info("캘린더 동기화 시작")
   try:
       calendar_logger.info(f"사용자 {current_user.email}의 캘린더 동기화 요청")
       
       # refresh token으로 새 access token 획득
       calendar_logger.info("새로운 액세스 토큰 요청")
       new_access_token = await refresh_google_token(current_user.refresh_token)
       calendar_logger.info("새로운 액세스 토큰 발급 완료")
       
       # 캘린더 동기화
       calendar_logger.info("DynamoDB에 캘린더 데이터 동기화 시작")
       await put_calendar_list(new_access_token)
       calendar_logger.info("캘린더 데이터 동기화 완료")
       
       return {
           "success": True,
           "message": "캘린더 동기화가 성공적으로 완료되었습니다"
       }
   except Exception as e:
       calendar_logger.error(f"캘린더 동기화 중 오류 발생: {str(e)}")
       calendar_logger.error(f"상세 에러 정보: {traceback.format_exc()}")
       raise HTTPException(
           status_code=500, 
           detail=f"캘린더 동기화 실패: {str(e)}"
       )

@router.post("/sync-events")
async def sync_events(current_user: User = Depends(get_current_user)):
    calendar_logger.info("이벤트 동기화 시작")
    try:
        calendar_logger.info(f"사용자 {current_user.email}의 이벤트 동기화 요청")
        
        # refresh token으로 새 access token 획득
        calendar_logger.info("새로운 액세스 토큰 요청")
        new_access_token = await refresh_google_token(current_user.refresh_token)
        calendar_logger.info("새로운 액세스 토큰 발급 완료")
        
        # 이벤트 동기화 (기존에 만든 함수 사용)
        calendar_logger.info("DynamoDB에 이벤트 데이터 동기화 시작")
        await store_calendar_events(current_user.email, new_access_token)
        calendar_logger.info("이벤트 데이터 동기화 완료")
        
        return {
            "success": True,
            "message": "이벤트 동기화가 성공적으로 완료되었습니다"
        }
    except Exception as e:
        calendar_logger.error(f"이벤트 동기화 중 오류 발생: {str(e)}")
        calendar_logger.error(f"상세 에러 정보: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"이벤트 동기화 실패: {str(e)}"
        )
    
### 캘린더 API
# 1. 캘린더 데이터 요청
# 2. 전처리
# 3. dynamodb에 비동기로 삽입
# 4. 프론트로 데이터 return

@router.get("/dashboard-data")
async def get_dashboard_data(code):
    # token_info 예시는 print 후 확인 요망
    token_info = await google.get_access_token(code)


    # 1. 캘린더 데이터 요청
    calendar_data_origin = await google.get_calendar_data(code)

    # 2. 전처리
    # data_preprocessing.py 내부 함수 참고

    # 3. dynamodb 비동기 삽입
    # data_preprocessing.py 내부 함수 참고
    
    # 4. 프론트로 리턴
    # 2번에서 전처리 한 결과 리턴해주면 됨
    # 향후 프론트에서 이 데이터 받아서 알아서 잘 각 시각화 component에 잘 매핑





#### 켈린더 데이터 전처리 함수
async def process_weekly_activity_data(data: dict) -> dict:
    calendar_logger.info("주간 이벤트 데이터 전처리 시작")
    calendar_logger.info(f"받은 데이터: {data}")
    
    try:
        events = data.get('events', [])
        calendar_logger.info(f"총 이벤트 수: {len(events)}")
        
        try:
            this_week_start = datetime.strptime(data['this_week_start'], '%Y-%m-%dT%H:%M:%S%z')
            last_week_start = datetime.strptime(data['last_week_start'], '%Y-%m-%dT%H:%M:%S%z')
            calendar_logger.info(f"날짜 파싱 결과 - 이번 주: {this_week_start}, 지난 주: {last_week_start}")
        except ValueError as e:
            calendar_logger.error(f"날짜 파싱 오류: {e}")
            raise
        
        this_week_events = []
        last_week_events = []
        
        kst = pytz.timezone('Asia/Seoul')
        
        for event in events:
            try:
                if 'start' not in event or 'end' not in event:
                    calendar_logger.warning(f"시작/종료 시간이 없는 이벤트 건너뜀: {event}")
                    continue
                
                start = event['start'].get('dateTime')
                end = event['end'].get('dateTime')
                
                if not start or not end:
                    calendar_logger.warning(f"유효하지 않은 시간을 가진 이벤트 건너뜀: {event}")
                    continue
                
                calendar_logger.info(f"이벤트 처리 중: {event.get('summary', '제목 없음')}")
                calendar_logger.info(f"원본 시간 - 시작: {start}, 종료: {end}")
                
                # 시간 변환 및 KST 적용
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(kst)
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(kst)
                
                event_data = {
                    'day': start_dt.weekday(),
                    'startTime': round(start_dt.hour + start_dt.minute / 60, 2),
                    'endTime': round(end_dt.hour + end_dt.minute / 60, 2),
                    'duration': round((end_dt - start_dt).total_seconds() / 3600, 2)
                }
                calendar_logger.info(f"처리된 이벤트 데이터: {event_data}")
                
                event_start_date = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                
                if this_week_start <= event_start_date < this_week_start + timedelta(days=7):
                    this_week_events.append(event_data)
                    calendar_logger.info("이번 주 이벤트로 추가됨")
                elif last_week_start <= event_start_date < last_week_start + timedelta(days=7):
                    last_week_events.append(event_data)
                    calendar_logger.info("지난 주 이벤트로 추가됨")
                
            except Exception as e:
                calendar_logger.error(f"이벤트 처리 중 오류 발생: {e}")
                continue
        
        result = {
            'this_week': this_week_events,
            'last_week': last_week_events
        }
        calendar_logger.info(f"최종 처리 결과: {result}")
        return result
        
    except Exception as e:
        calendar_logger.error(f"데이터 전처리 중 오류 발생: {str(e)}")
        calendar_logger.error(f"상세 오류 내용: {traceback.format_exc()}")
        return {'this_week': [], 'last_week': []}

@router.get("/weekly-activity")
async def get_weekly_activity(current_user: User = Depends(get_current_user)):
    calendar_logger.info(f"사용자 {current_user.email}의 주간 활동 데이터 요청")
    try:
        # DynamoDB에서 이벤트 데이터 조회
        raw_data = await get_weekly_activity_data(current_user.email)
        
        # 데이터 전처리
        processed_data = await process_weekly_activity_data(raw_data)
        
        return {
            "success": True,
            "data": processed_data
        }
        
    except Exception as e:
        calendar_logger.error(f"주간 활동 데이터 조회 중 오류 발생: {str(e)}")
        calendar_logger.error(f"상세 에러: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="주간 활동 데이터 조회 실패"
        )