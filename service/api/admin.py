from flask import Blueprint, Response, render_template, request, jsonify, redirect, url_for
import requests
from sqlalchemy.orm import query
from sqlalchemy.sql import func
from service.database.models import AdminUser,Config, Notice, Payment,ProdCag,ProdInfo,Card,Order
from service.api.db import db
from service.util.backup.sql import main_back   #信息备份

import bcrypt
# 添加jwt
from flask_jwt_extended import (
    JWTManager, jwt_required, create_access_token
)
import os
# from werkzeug.utils import secure_filename  #主要作用，使文件上传更安全

# 图片公共路径
UPLOAD_PATH = os.path.join(os.path.dirname(__file__),'../../public/images')


#日志记录
from service.util.log import log

admin = Blueprint('admin', __name__,url_prefix='/api/v4')



@admin.route('/')
def index():
    return 'admin hello'


import time
from functools import wraps

def timefn(fn):
    """计算性能的修饰器"""
    @wraps(fn)
    def measure_time(*args, **kwargs):
        t1 = time.time()
        result = fn(*args, **kwargs)
        t2 = time.time()
        print(f"@timefn: {fn.__name__} took {t2 - t1: .5f} s")
        return result
    return measure_time



@admin.route('/login', methods=['POST'])
def login():
    try:
        # start_t = time.time()
        email = request.json.get('email', None)
        password = request.json.get('password', None)
        if not email:
            return '邮箱参数丢失', 400
        if not password:
            return '密码参数丢失', 400
        user = AdminUser.query.filter_by(email=email).first()
        if not user:
            return '账号不存在或密码不正确', 404
        # 已知道mysql模式下使用utf8
        #if bcrypt.checkpw(password.encode('utf-8'), user.hash.encode('utf-8')):
        # sqlite模式下，起步没问题，后续需要移除hash的encode,因此采用下面的转换，可兼容mysql和sqlite
        try:
            user_defin = user.hash.encode('utf-8')
        except:
            user_defin = user.hash

        # print(time.time() - start_t)
        if bcrypt.checkpw(password.encode('utf-8'), user_defin):
            # print(time.time() - start_t)
            access_token = create_access_token(identity={"email": email})
            # print(time.time() - start_t)
            return {"access_token": access_token}, 200
        else:
            return '账号不存在或密码不正确2', 400
    except AttributeError as e:
        log(e)
        return 'Provide an Email and Password in JSON format in the request body', 400

# 图床参数
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg','gif' }
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@admin.route('/upload',methods=['POST'])
@jwt_required
def upload():
    file = request.files['file']
    # file = request.json.get('file', None)
    if not file:
        return '参数丢失', 400
    
    if allowed_file(file.filename):
        #secure_filename可以使上传文件的文件名更加安全，但是对中文的支持不是很好，如果想要使用secure_file()可以在使用之前将filename转换成英文或时间戳
        # filename = secure_filename(file.filename)
        filename = time.strftime('%Y-%m-%d_%H-%M-%S',time.localtime()) +'.' + file.filename.split('.')[-1]
        file.save(os.path.join(UPLOAD_PATH,filename))
        # print('上传成功'+filename)
        return jsonify({'msg':'success','info':filename})
    else:
        # print('上传失败')
        return 'faild'


@admin.route('/dashboard', methods=['get'])
@jwt_required
def dashboard():
    info = {}
    info['cag_num'] = len(ProdCag.query.filter().all()) #总分类
    info['shop_num'] = len(ProdInfo.query.filter().all())  #总商品
    info['card_num'] = len(Card.query.filter().all())  #总卡密
    info['order_num'] = len(Order.query.filter().all()) #总订单
    info['total_income'] = round(Order.query.with_entities(func.sum(Order.total_price)).scalar(),2)    #总收入
    info['total_num'] = int(Order.query.with_entities(func.sum(Order.num)).scalar())   #总销售数量--mysql模式下<Decimal('6')
    # 历史数据获取
    orders = Order.query.filter().all()
    info['history_date'] = [x.updatetime for x in orders]
    info['history_price'] = [x.total_price for x in orders]
    # info['top'] = [{}] #名称，销量，价格
    return jsonify(info)

@admin.route('/get_smtp', methods=['get'])
@jwt_required
def get_smtp():
    try:
        smtp = Notice.query.filter_by(id = 1).first()
        return jsonify(smtp.to_json())
    except Exception as e:
        log(e)
        return '数据库异常', 500    
    

@admin.route('/update_smtp', methods=['post'])
@jwt_required
def update_smtp():
    data = request.json.get('data', None)
    if not data:
        return 'Missing data', 400
    # 密码加密存储
    try:
        Notice.query.filter_by(id =1).update({'config':str(data['config'])})
        db.session.commit()        
    except Exception as e:
        log(e)
        return '数据库异常', 500      
    # 重定向登录界面
    return '邮箱更新成功', 200

@admin.route('/test_smtp', methods=['post'])
@jwt_required
def test_smtp():
    # print(request.json)
    email = request.json.get('email', None)
    message = request.json.get('message', None)
    data = request.json.get('data', None)
    if not all([email,message,data]):
        return 'Missing data', 400
    # 调用smtp函数发送邮件
    try:
        from service.util.message.smtp import mail_test
        if mail_test(config=data['config'],message=message,email=email):
            return '邮件已发送', 200
        else:
            return '邮件发送失败', 400
    except Exception as e:
        log(e)
        return '邮箱配置可能有错误', 400      


# 分类增删改查
@admin.route('/update_class', methods=['post']) #增、删、改；查询的使用get方式
@jwt_required
def update_class():
    # print(request.json)
    id = request.json.get('id', None)
    name = request.json.get('name', None)
    info = request.json.get('info', None)
    sort = request.json.get('sort', None)
    methord = request.json.get('methord', None) #update,add,delete
    print(methord)
    if methord not in ['update','delete','add']:
        return 'Missing data 1', 400
    # 调用smtp函数发送邮件
    try:
        if methord == 'update':
            if not id or not name or not info or not sort:
                return 'Missing data', 400
            ProdCag.query.filter_by(id = id).update({'name':name,'info':info,'sort':sort})
        elif methord == 'delete':
            if not id:
                return 'Missing data', 400
            ProdCag.query.filter_by(id = id).delete()
        else:
            if not name or not info or not sort:
                return 'Missing data 2', 400
            new_cag = ProdCag(name,info,sort)
            db.session.add(new_cag)
        db.session.commit()
    except Exception as e:
        log(e)
        return '数据库异常', 500        

    # 重定向登录界面
    return '修改成功', 200

@admin.route('/get_class', methods=['get']) #分类查询
@jwt_required
def get_class():
    try:
        prod_cags = ProdCag.query.filter().all()
    except Exception as e:
        log(e)
        return '数据库异常', 500        
    
    return jsonify([x.to_json() for x in prod_cags])    

@admin.route('/get_shop', methods=['get']) #商品查询
@jwt_required
def get_shop():
    try:
        prod_shops = ProdInfo.query.filter().all()
    except Exception as e:
        log(e)
        return '数据库异常', 500        
    return jsonify([x.admin_json() for x in prod_shops])   

@admin.route('/get_shop_edit', methods=['post']) #商品全部信息返回
@jwt_required
def get_shop_edit():
    # print(request.json)
    id = request.json.get('id', None)
    if not id:
        return 'Missing data', 400
    try:
        prod_shop = ProdInfo.query.filter_by(id = id).first()
        prod_cags = ProdCag.query.filter().all()    #获取分类
    except Exception as e:
        log(e)
        return '数据库异常', 500            
    info = prod_shop.admin_edit()
    info['cags'] = [x.to_json()['name'] for x in prod_cags]
    # prod_shop['cags'] = [x.to_json()['name'] for x in prod_cags]
    return jsonify(info)   

@admin.route('/update_shop', methods=['post']) #增、删、改；查询的使用get方式
@jwt_required
def update_shop():
    
    id = request.json.get('id', None)
    cag_name = request.json.get('cag_name', None)
    name = request.json.get('name', None)
    info = request.json.get('info', None)
    img_url = request.json.get('img_url', None)
    sort = request.json.get('sort', None)
    discription = request.json.get('discription', None)
    price = request.json.get('price', None)
    auto = request.json.get('auto', None)
    sales = request.json.get('sales', None)
    tag = request.json.get('tag', None)
    isactive = request.json.get('isactive', None)
    methord = request.json.get('methord', None) #update,add,delete
    if methord not in ['update','delete','add']:
        return 'Missing data1', 400
    # 调用smtp函数发送邮件
    try:
        if methord == 'update':
            if not all([id,cag_name,name,img_url,sort,discription,price,tag]):   #因修改时auto和isactive报错缺失，移除
                return 'Missing data2', 400
            ProdInfo.query.filter_by(id = id).update({'cag_name':cag_name,'name':name,'info':info,'img_url':img_url,'sort':sort,'discription':discription,'price':price,'auto':auto,'tag':tag,'isactive':isactive})
        elif methord == 'delete':
            if not id:
                return 'Missing data', 400
            ProdInfo.query.filter_by(id = id).delete()
        else:
            if not name or not info or not sort:
                return 'Missing data', 400
            new_prod = ProdInfo(cag_name,name,info,img_url,sort,discription,price,auto,sales,tag,isactive)
            db.session.add(new_prod)
        db.session.commit()        
    except Exception as e:
        log(e)
        return '数据库异常', 500      

    # 
    return '修改成功', 200

@admin.route('/get_card', methods=['get']) #卡密查询
def get_card():
    try:
        cards = Card.query.filter().all()
    except Exception as e:
        log(e)
        return '数据库异常', 500      
    return jsonify([x.to_json() for x in cards])   

@admin.route('/update_card', methods=['post']) #卡密查询
@jwt_required
def update_card():
    # print(request.json)
    id = request.json.get('id', None)
    prod_name = request.json.get('prod_name', None)
    card = request.json.get('card', None)
    isused = request.json.get('isused', None)
    reuse = request.json.get('reuse', None)
    methord = request.json.get('methord', None) #update,add,delete
    if methord not in ['update','delete','add','add_all']:
        return 'Missing methord', 400
    # 调用smtp函数发送邮件
    try:
        if methord == 'update':
            if not id or not prod_name or not card:
                return 'Missing data 1', 400
            Card.query.filter_by(id = id).update({'prod_name':prod_name,'card':card,'isused':isused,'reuse':reuse})
        elif methord == 'delete':
            if not id:
                return 'Missing data', 400
            Card.query.filter_by(id = id).delete()
        # elif methord == 'add':
        else:
            if not all([prod_name,card]):
                return 'Missing data', 400
            # print(card.split('\n'))
            tmp_cards = list(filter(None,card.split('\n')))
            if len(tmp_cards) >1:
                reuse = False
            db.session.add_all([Card(prod_name,card=x,isused=0,reuse=reuse) for x in tmp_cards])
        db.session.commit()
        # 重定向登录界面
        return '修改成功', 200          
    except Exception as e:
        log(e)
        return '数据库异常', 500       

  



@admin.route('/remove_cards', methods=['post']) #批量删除卡密
@jwt_required
def remove_cards():
    ids = request.json.get('ids', None)
    if not ids:
        return 'Missing Data', 400
    [Card.query.filter_by(id = x).delete() for x in ids]    
    db.session.commit()
    return '批量删除', 200    


@admin.route('/get_orders', methods=['get']) #已售订单信息
@jwt_required
def get_orders():
    try:
        orders = Order.query.filter().all()
    except Exception as e:
        log(e)
        return '数据库异常', 500      
    return jsonify([x.admin_json() for x in orders])   


@admin.route('/get_pays', methods=['get']) #支付接口
@jwt_required
def get_pays():
    try:
        pays = Payment.query.filter().all()
    except Exception as e:
        log(e)
        return '数据库异常', 500      
    return jsonify([x.enable_json() for x in pays])   

@admin.route('/update_pays', methods=['get','post']) #支付接口get获取详细信息，post升级更新
@jwt_required
def update_pays():
    try:
        if request.method == 'GET':
            pay_id = request.args.get('id')
            return jsonify(Payment.query.filter_by(id = pay_id).first().all_json())
        else:
            # print(request.json)
            data = request.json.get('data',None)
            if not data:
                return 'Missing Data', 400
            # print(type(data['config']))
            Payment.query.filter_by(id = data['id']).update({'icon':data['icon'],'config':str(data['config']),'isactive':data['isactive']})
            db.session.commit()
            return '修改成功', 200 
    except Exception as e:
        log(e)
        return '数据库异常', 500      


@admin.route('/get_notice', methods=['get']) #通知接口
@jwt_required
def get_notice():
    try:
        notices = Notice.query.filter().all()
    except Exception as e:
        log(e)
        return '数据库异常', 500          
    return jsonify([x.to_json() for x in notices])   

@admin.route('/update_notice', methods=['post']) #通知接口
@jwt_required
def update_notice():
    data = request.json.get('data', None)
    if not data:
        return 'Missing Data', 400
    #数组数据更新--->两字典判断是否相等，不相等则更新
    try:
        old_data = [x.to_json() for x in Notice.query.filter().all()]
        for (i,index) in enumerate(data):
            if old_data[i] == index:
                pass    #数据未更新
            else:
                Notice.query.filter_by(id = index['id']).update({'config':str(index['config']),'admin_account':index['admin_account'],'admin_switch':index['admin_switch'],'user_switch':index['user_switch']})
        db.session.commit()
    except Exception as e:
        log(e)
        return '数据库异常', 500        

    return '修改成功', 200 


@admin.route('/get_admin_account', methods=['post']) #管理员
@jwt_required
def get_admin_account():
    return jsonify(AdminUser.query.filter_by(id = 1).first().to_json())   


@admin.route('/update_admin_account', methods=['post']) #管理员
@jwt_required
def update_admin_account():
    email = request.json.get('email', None)
    password = request.json.get('password', None) #传入卡密列表   
    if not all([email,password]):
        return '参数丢失', 400
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    AdminUser.query.filter_by(id = 1).update({'email':email,'hash':hashed})
    db.session.commit()
    return {"mgs": 'success'}, 200


@admin.route('/get_system', methods=['post']) #
@jwt_required
def get_system():
    res = Config.query.filter().all()
    return jsonify([x.to_json() for x in res])

@admin.route('/update_system', methods=['post']) #管理员
@jwt_required
def update_system():
    data = request.json.get('data', None)
    if not data:
        return '参数丢失', 400
    Config.query.filter_by(id = data['id']).update({'info':data['info']})
    db.session.commit()
    return {"mgs": 'success'}, 200



@admin.route('/demo', methods=['get']) #已售订单信息
@jwt_required
def demo():
    return jsonify(round(sum([float(x.total_price) for x in Order.query.filter().all()]),2))   


@admin.route('/backups',methods=['POST'])
@jwt_required
def backups():
    main_back()
    return {"mgs": 'success'}, 200


# def login():
#     username = request.form['username']
#     password = request.form['password']
#     user = User.query.filter_by(username=username, password=password).first()
#     if user is not None:
#         session_util.login_success(user)
#         return jsonify(Msg(True, gettext('login success')))
#     return jsonify(Msg(False, gettext('username or password wrong')))


# @base_bp.route('/logout', methods=['GET', 'POST'])
# def logout():
#     session_util.logout()
#     return redirect(url_for('base.index'))


# @base_bp.route('/robots.txt')
# def robots():
#     return Response('User-agent: *\n' + 'Disallow: /', 200, headers={
#         'Content-Type': 'text/plain'
#     })


# def init_user():
#     if User.query.count() == 0:
#         db.session.add(User('admin', 'admin'))
#         db.session.commit()


# init_user()
