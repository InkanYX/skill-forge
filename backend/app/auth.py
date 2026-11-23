"""Local password login. No public registration, email, or SMS provider."""
import argparse
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4, UUID
from typing import Annotated
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import select, update, delete, func, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import UserAccount, LoginSession, ModelConfiguration, ImageConfiguration, ImageJob

COOKIE='sf_login'
SESSION_SECONDS=12*60*60

def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def hash_password(password):
    salt=secrets.token_hex(16)
    value=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=32768,r=8,p=1,dklen=32,maxmem=64*1024*1024)
    return f'scrypt$32768$8$1${salt}${value.hex()}'
def verify_password(password,encoded):
    try:
        algorithm,n,r,p,salt,expected=encoded.split('$')
        if algorithm!='scrypt' or (n,r,p)!=('32768','8','1'): return False
        actual=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=int(n),r=int(r),p=int(p),dklen=32,maxmem=64*1024*1024)
        return hmac.compare_digest(actual,bytes.fromhex(expected))
    except (ValueError,TypeError): return False

def user_view(row):
    return {name:getattr(row,name) for name in ('id','username','display_name','role','is_active','must_change_password','created_at')}

def initialize_admin(engine,username,password):
    data=NewUser(username=username,display_name='管理员',password=password)
    with Session(engine) as session,session.begin():
        if engine.dialect.name=='postgresql': session.execute(text('SELECT pg_advisory_xact_lock(734905121)'))
        if session.scalar(select(func.count()).select_from(UserAccount)):
            raise HTTPException(409,'管理员已经初始化，不能重复初始化。')
        row=UserAccount(id=str(uuid4()),username=data.username,display_name=data.display_name,password_hash=hash_password(password),role='admin',is_active=True,must_change_password=True,failed_attempts=0,locked_until=0,created_at=now())
        session.add(row);session.flush()
        session.execute(update(ModelConfiguration).where(ModelConfiguration.owner_id.is_(None)).values(owner_id=row.id))
        return user_view(row)

class LoginInput(BaseModel):
    username:str=Field(min_length=1,max_length=32)
    password:SecretStr=Field(min_length=1,max_length=128)
class NewUser(BaseModel):
    username:str=Field(min_length=3,max_length=32,pattern=r'^[A-Za-z0-9_.-]+$')
    display_name:str=Field(default='',max_length=80)
    password:SecretStr|None=Field(default=None,min_length=8,max_length=128)
    @field_validator('username')
    @classmethod
    def normalize(cls,value): return value.lower()
class UserUpdate(BaseModel):
    display_name:str=Field(min_length=1,max_length=80)
    is_active:bool
class PasswordChange(BaseModel):
    current_password:SecretStr=Field(min_length=1,max_length=128)
    new_password:SecretStr=Field(min_length=8,max_length=128)

class AuthService:
    def __init__(self,engine,image_store):
        self.engine,self.image_store=engine,image_store
        self.lock=RLock();self.attempts={}
        self.dummy_hash=hash_password('unused-timing-reference-password')
    def require_db(self):
        if self.engine is None: raise HTTPException(503,'请配置数据库并执行迁移。')
    def current(self,token):
        if not token or len(token)!=43 or self.engine is None:return None
        with Session(self.engine) as session:
            login=session.get(LoginSession,digest(token))
            if not login or login.expires_at<time.time():return None
            user=session.get(UserAccount,login.user_id)
            return user_view(user) if user and user.is_active else None
    def set_cookie(self,response,token,request):
        response.set_cookie(COOKIE,token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=SESSION_SECONDS,path='/')
    def new_session(self,session,user_id):
        token=secrets.token_urlsafe(32)
        session.execute(delete(LoginSession).where(LoginSession.expires_at<time.time()))
        session.add(LoginSession(token_hash=digest(token),user_id=user_id,expires_at=time.time()+SESSION_SECONDS))
        return token
    def rate_limit(self,request):
        address=request.client.host if request.client else 'local'
        with self.lock:
            current=time.time();values=[item for item in self.attempts.get(address,[]) if item>current-900]
            if len(values)>=30: raise HTTPException(429,'登录尝试过多，请稍后重试。')
            if len(self.attempts)>1000:self.attempts.clear()
            self.attempts[address]=values+[current]
    def revoke(self,session,user_id):
        session.execute(delete(LoginSession).where(LoginSession.user_id==user_id))
        session.execute(update(ImageJob).where(ImageJob.owner_id==user_id,ImageJob.status=='queued').values(status='cancelled',message='账号凭据已变更或账号被停用，排队项未调用服务商。',encrypted_key='',updated_at=now()))
        identifiers=list(session.scalars(select(ImageConfiguration.id).where(ImageConfiguration.owner==user_id)))
        with self.image_store.lock:
            for identifier in identifiers:self.image_store.keys.pop(identifier,None)
    def claim_browser_profile(self,session,user,request):
        if user.role!='admin':return
        old=request.cookies.get('sf_image_session','')
        if len(old)!=43:return
        legacy=session.scalar(select(ImageConfiguration).where(ImageConfiguration.owner==digest(old)).with_for_update())
        own=session.scalar(select(ImageConfiguration.id).where(ImageConfiguration.owner==user.id))
        if legacy and not own:legacy.owner=user.id


def build_auth_router(service):
    router=APIRouter(prefix='/api',tags=['accounts'])
    def admin(request):
        user=getattr(request.state,'user',None)
        if not user or user['role']!='admin':raise HTTPException(403,'此功能仅限管理员。')
        return user
    @router.get('/auth/me')
    def me(request:Request):
        service.require_db()
        user=service.current(request.cookies.get(COOKIE))
        with Session(service.engine) as session:
            setup=session.scalar(select(func.count()).select_from(UserAccount))==0
        return {'authenticated':bool(user),'user':user,'setup_required':setup}
    @router.post('/auth/login')
    def login(request:Request,response:Response,data:LoginInput):
        service.require_db();service.rate_limit(request)
        failed=False
        with Session(service.engine) as session,session.begin():
            row=session.scalar(select(UserAccount).where(UserAccount.username==data.username.strip().lower()).with_for_update())
            valid=verify_password(data.password.get_secret_value(),row.password_hash if row else service.dummy_hash)
            if not row or not row.is_active or row.locked_until>time.time() or not valid:
                if row:
                    row.failed_attempts+=1
                    if row.failed_attempts>=7:row.locked_until=time.time()+900;row.failed_attempts=0
                failed=True
            else:
                row.failed_attempts=0;row.locked_until=0
                token=service.new_session(session,row.id);service.claim_browser_profile(session,row,request)
                result=user_view(row)
        if failed:raise HTTPException(401,'账号或密码不正确，或账号暂不可用。')
        service.set_cookie(response,token,request)
        return result
    @router.post('/auth/logout')
    def logout(request:Request,response:Response):
        service.require_db()
        with Session(service.engine) as session,session.begin():
            session.execute(delete(LoginSession).where(LoginSession.token_hash==digest(request.cookies.get(COOKIE,''))))
        response.delete_cookie(COOKIE,path='/')
        return {'message':'已退出登录。'}
    @router.post('/auth/password')
    def password(request:Request,response:Response,data:PasswordChange):
        service.require_db()
        current=service.current(request.cookies.get(COOKIE))
        if not current:raise HTTPException(401,'请先登录。')
        with Session(service.engine) as session,session.begin():
            row=session.get(UserAccount,current['id'],with_for_update=True)
            if not verify_password(data.current_password.get_secret_value(),row.password_hash):raise HTTPException(400,'当前密码不正确。')
            if data.new_password.get_secret_value()==data.current_password.get_secret_value():raise HTTPException(422,'新密码不能与当前密码相同。')
            row.password_hash=hash_password(data.new_password.get_secret_value());row.must_change_password=False
            service.revoke(session,row.id)
            token=service.new_session(session,row.id);result=user_view(row)
        service.set_cookie(response,token,request)
        return result
    @router.get('/admin/users')
    def list_users(request:Request):
        admin(request)
        with Session(service.engine) as session:
            return [user_view(row) for row in session.scalars(select(UserAccount).order_by(UserAccount.created_at))]
    @router.post('/admin/users',status_code=201)
    def create_user(request:Request,data:NewUser):
        admin(request);password=data.password.get_secret_value() if data.password else secrets.token_urlsafe(15)
        try:
            with Session(service.engine) as session,session.begin():
                row=UserAccount(id=str(uuid4()),username=data.username,display_name=data.display_name.strip() or data.username,password_hash=hash_password(password),role='member',is_active=True,must_change_password=True,failed_attempts=0,locked_until=0,created_at=now())
                session.add(row);session.flush();result=user_view(row)
        except IntegrityError:raise HTTPException(409,'账号已存在。') from None
        return {'user':result,'temporary_password':password}
    @router.put('/admin/users/{identifier}')
    def update_user(request:Request,identifier:UUID,data:UserUpdate):
        actor=admin(request)
        with Session(service.engine) as session,session.begin():
            row=session.get(UserAccount,str(identifier),with_for_update=True)
            if not row:raise HTTPException(404,'成员不存在。')
            if row.role=='admin' and not data.is_active:raise HTTPException(409,'不能停用管理员账号。')
            row.display_name=data.display_name.strip() or row.username
            if row.is_active and not data.is_active:service.revoke(session,row.id)
            row.is_active=data.is_active
            return user_view(row)
    @router.post('/admin/users/{identifier}/reset-password')
    def reset_password(request:Request,identifier:UUID):
        actor=admin(request)
        with Session(service.engine) as session,session.begin():
            row=session.get(UserAccount,str(identifier),with_for_update=True)
            if not row:raise HTTPException(404,'成员不存在。')
            if row.id==actor['id']:raise HTTPException(409,'请使用修改密码功能修改自己的密码。')
            password=secrets.token_urlsafe(15);row.password_hash=hash_password(password)
            row.must_change_password=True;row.failed_attempts=0;row.locked_until=0
            service.revoke(session,row.id)
            return {'user':user_view(row),'temporary_password':password}
    return router


def main():
    from app.database import database_url,make_engine
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['init-admin','reset-admin-password']);parser.add_argument('--username',default='admin')
    args=parser.parse_args();engine=make_engine(database_url())
    try:
        temporary=secrets.token_urlsafe(15)
        if args.action=='init-admin':
            user=initialize_admin(engine,args.username,temporary)
        else:
            with Session(engine) as session,session.begin():
                row=session.scalar(select(UserAccount).where(UserAccount.username==args.username.lower(),UserAccount.role=='admin').with_for_update())
                if not row:raise HTTPException(404,'管理员账号不存在。')
                row.password_hash=hash_password(temporary);row.must_change_password=True;row.failed_attempts=0;row.locked_until=0
                session.execute(delete(LoginSession).where(LoginSession.user_id==row.id))
                session.execute(update(ImageJob).where(ImageJob.owner_id==row.id,ImageJob.status=='queued').values(status='cancelled',message='管理员密码已重置，排队项未调用服务商。',encrypted_key='',updated_at=now()))
                user=user_view(row)
        print('管理员账号：'+user['username']);print('一次性初始密码：'+temporary);print('首次登录必须修改密码。密码只显示本次，不写入文件。')
    except HTTPException as error:print(error.detail);raise SystemExit(1) from None
    finally:engine.dispose()

if __name__=='__main__':main()
