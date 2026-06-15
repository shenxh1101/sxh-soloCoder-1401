from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from datetime import datetime, timedelta
import os
import csv
import io

from database import db

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'gas-station-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'gas_station.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

from models import *
from utils import *

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    fuels = Fuel.query.all()
    inventory_data = []
    warnings = []
    
    for fuel in fuels:
        current_stock = get_current_stock(fuel.id)
        avg_cost = get_moving_average_cost(fuel.id)
        predicted_24h = predict_24h_sales(fuel.id)
        stock_days = current_stock / predicted_24h if predicted_24h > 0 else 0
        
        fuel_data = {
            'id': fuel.id,
            'name': fuel.name,
            'code': fuel.code,
            'current_stock': round(current_stock, 2),
            'capacity': fuel.tank_capacity,
            'stock_percent': round((current_stock / fuel.tank_capacity) * 100, 1),
            'avg_cost': round(avg_cost, 3),
            'current_price': round(fuel.current_price, 2),
            'predicted_24h': round(predicted_24h, 2),
            'stock_days': round(stock_days, 1),
            'competitor_price': get_latest_competitor_price(fuel.id)
        }
        inventory_data.append(fuel_data)
        
        if predicted_24h > current_stock:
            shortage = predicted_24h - current_stock
            suggested_order = shortage + (fuel.tank_capacity * 0.3)
            warnings.append({
                'fuel_name': fuel.name,
                'shortage': round(shortage, 2),
                'suggested_order': round(suggested_order, 2),
                'level': 'danger'
            })
        elif stock_days < 2:
            warnings.append({
                'fuel_name': fuel.name,
                'shortage': 0,
                'suggested_order': round(fuel.tank_capacity * 0.5, 2),
                'level': 'warning'
            })
    
    today = datetime.now().date()
    today_sales = get_daily_sales(today)
    today_revenue = sum(s['revenue'] for s in today_sales.values()) if today_sales else 0
    today_profit = sum(s['profit'] for s in today_sales.values()) if today_sales else 0
    
    price_histories = PriceHistory.query.order_by(PriceHistory.change_time.desc()).limit(10).all()
    
    return render_template('dashboard.html',
                         inventory_data=inventory_data,
                         warnings=warnings,
                         today_revenue=round(today_revenue, 2),
                         today_profit=round(today_profit, 2),
                         price_histories=price_histories)

@app.route('/intake', methods=['GET', 'POST'])
def intake():
    if request.method == 'POST':
        fuel_id = int(request.form['fuel_id'])
        volume = float(request.form['volume'])
        cost_price = float(request.form['cost_price'])
        supplier = request.form.get('supplier', '')
        truck_no = request.form.get('truck_no', '')
        
        intake_record = IntakeRecord(
            fuel_id=fuel_id,
            volume=volume,
            cost_price=cost_price,
            supplier=supplier,
            truck_no=truck_no,
            intake_time=datetime.now()
        )
        db.session.add(intake_record)
        db.session.commit()
        
        flash(f'成功录入 {volume:.0f} 升 {Fuel.query.get(fuel_id).name}，成本价 {cost_price:.3f} 元/升', 'success')
        return redirect(url_for('intake'))
    
    fuels = Fuel.query.all()
    intake_records = IntakeRecord.query.order_by(IntakeRecord.intake_time.desc()).limit(20).all()
    
    return render_template('intake.html', 
                         fuels=fuels, 
                         intake_records=intake_records)

@app.route('/pricing', methods=['GET', 'POST'])
def pricing():
    if request.method == 'POST':
        fuel_id = int(request.form['fuel_id'])
        new_price = float(request.form['new_price'])
        reason = request.form.get('reason', '手动调整')
        
        fuel = Fuel.query.get(fuel_id)
        old_price = fuel.current_price
        
        if abs(new_price - old_price) < 0.001:
            flash(f'{fuel.name} 价格无需调整，已为 {new_price:.2f} 元/升', 'info')
            return redirect(url_for('pricing'))
        
        fuel.current_price = new_price
        fuel.price_update_time = datetime.now()
        
        price_history = PriceHistory(
            fuel_id=fuel_id,
            old_price=old_price,
            new_price=new_price,
            change_time=datetime.now(),
            change_type='manual',
            reason=reason
        )
        db.session.add(price_history)
        db.session.commit()
        
        flash(f'{fuel.name} 价格已从 {old_price:.2f} 调整为 {new_price:.2f} 元/升', 'success')
        return redirect(url_for('pricing'))
    
    fuels = Fuel.query.all()
    pricing_rules = PricingRule.query.all()
    price_histories = PriceHistory.query.order_by(PriceHistory.change_time.desc()).limit(30).all()
    
    competitor_prices = {}
    auto_price_previews = {}
    rule_map = {r.fuel_id: r for r in pricing_rules}
    
    for fuel in fuels:
        comp_info = get_latest_competitor_price_info(fuel.id)
        competitor_prices[fuel.id] = comp_info
        
        rule = rule_map.get(fuel.id)
        if rule and rule.is_active and comp_info:
            preview_price = calculate_auto_price(fuel.id, rule)
            if preview_price is not None:
                auto_price_previews[fuel.id] = {
                    'current_price': fuel.current_price,
                    'competitor_price': comp_info['price'],
                    'rule_type': rule.rule_type,
                    'rule_type_name': rule.rule_type_name,
                    'price_diff': rule.price_diff,
                    'preview_price': preview_price,
                    'price_change': round(preview_price - fuel.current_price, 2),
                    'change_pct': round((preview_price - fuel.current_price) / fuel.current_price * 100, 2)
                }
    
    return render_template('pricing.html',
                         fuels=fuels,
                         pricing_rules=pricing_rules,
                         price_histories=price_histories,
                         competitor_prices=competitor_prices,
                         auto_price_previews=auto_price_previews)

@app.route('/pricing/rules', methods=['POST'])
def pricing_rules():
    fuel_id = int(request.form['fuel_id'])
    rule_type = request.form['rule_type']
    price_diff = float(request.form.get('price_diff', 0))
    is_active = 'is_active' in request.form
    
    rule = PricingRule.query.filter_by(fuel_id=fuel_id).first()
    if rule:
        rule.rule_type = rule_type
        rule.price_diff = price_diff
        rule.is_active = is_active
    else:
        rule = PricingRule(
            fuel_id=fuel_id,
            rule_type=rule_type,
            price_diff=price_diff,
            is_active=is_active
        )
        db.session.add(rule)
    db.session.commit()
    
    flash('定价规则已更新', 'success')
    return redirect(url_for('pricing'))

@app.route('/pricing/auto_apply/<int:fuel_id>')
def auto_apply_pricing(fuel_id):
    fuel = Fuel.query.get(fuel_id)
    rule = PricingRule.query.filter_by(fuel_id=fuel_id, is_active=True).first()
    
    if not rule:
        flash('该油品没有启用的自动定价规则', 'error')
        return redirect(url_for('pricing'))
    
    competitor_price = get_latest_competitor_price(fuel_id)
    if competitor_price is None:
        flash('没有竞争对手价格数据，请先导入CSV', 'error')
        return redirect(url_for('pricing'))
    
    old_price = fuel.current_price
    
    if rule.rule_type == 'lower':
        new_price = competitor_price - rule.price_diff
    elif rule.rule_type == 'higher':
        new_price = competitor_price + rule.price_diff
    else:
        new_price = competitor_price
    
    new_price = round(new_price, 2)
    
    if abs(new_price - old_price) < 0.001:
        flash(f'{fuel.name} 价格无需调整，已为 {new_price:.2f} 元/升', 'info')
        return redirect(url_for('pricing'))
    
    fuel.current_price = new_price
    fuel.price_update_time = datetime.now()
    
    if rule.rule_type == 'same':
        reason_text = '自动定价：与竞争对手价格持平'
    else:
        reason_text = f'自动定价：比竞争对手{rule.rule_type_name}{abs(rule.price_diff):.2f}元'
    
    price_history = PriceHistory(
        fuel_id=fuel_id,
        old_price=old_price,
        new_price=new_price,
        change_time=datetime.now(),
        change_type='auto',
        reason=reason_text
    )
    db.session.add(price_history)
    db.session.commit()
    
    flash(f'自动定价已应用，{fuel.name} 新价格为 {new_price:.2f} 元/升', 'success')
    return redirect(url_for('pricing'))

@app.route('/pricing/batch_preview')
def batch_preview_pricing():
    fuels = Fuel.query.all()
    rule_map = {r.fuel_id: r for r in PricingRule.query.filter_by(is_active=True).all()}
    
    preview_data = []
    for fuel in fuels:
        comp_price = get_latest_competitor_price(fuel.id)
        rule = rule_map.get(fuel.id)
        
        if comp_price is None:
            preview_data.append({
                'fuel_id': fuel.id,
                'fuel_name': fuel.name,
                'current_price': fuel.current_price,
                'competitor_price': None,
                'preview_price': None,
                'price_change': None,
                'change_pct': None,
                'has_rule': rule is not None,
                'error': '无竞争对手价格'
            })
            continue
        
        if not rule:
            preview_data.append({
                'fuel_id': fuel.id,
                'fuel_name': fuel.name,
                'current_price': fuel.current_price,
                'competitor_price': comp_price,
                'preview_price': None,
                'price_change': None,
                'change_pct': None,
                'has_rule': False,
                'error': '无启用的定价规则'
            })
            continue
        
        preview_price = calculate_auto_price(fuel.id, rule)
        price_change = round(preview_price - fuel.current_price, 2)
        change_pct = round(price_change / fuel.current_price * 100, 2)
        
        preview_data.append({
            'fuel_id': fuel.id,
            'fuel_name': fuel.name,
            'current_price': fuel.current_price,
            'competitor_price': comp_price,
            'rule_type': rule.rule_type,
            'rule_type_name': rule.rule_type_name,
            'price_diff': rule.price_diff,
            'preview_price': preview_price,
            'price_change': price_change,
            'change_pct': change_pct,
            'has_rule': True,
            'needs_change': abs(price_change) >= 0.001
        })
    
    return jsonify({
        'success': True,
        'data': preview_data
    })

@app.route('/pricing/batch_apply', methods=['POST'])
def batch_apply_pricing():
    fuels = Fuel.query.all()
    rule_map = {r.fuel_id: r for r in PricingRule.query.filter_by(is_active=True).all()}
    
    applied_count = 0
    skipped_count = 0
    results = []
    now = datetime.now()
    
    for fuel in fuels:
        comp_price = get_latest_competitor_price(fuel.id)
        rule = rule_map.get(fuel.id)
        
        if comp_price is None or not rule:
            skipped_count += 1
            continue
        
        new_price = calculate_auto_price(fuel.id, rule)
        old_price = fuel.current_price
        
        if abs(new_price - old_price) < 0.001:
            skipped_count += 1
            results.append({
                'fuel_name': fuel.name,
                'status': 'skipped',
                'message': f'价格无需调整，已为 {new_price:.2f} 元/升'
            })
            continue
        
        fuel.current_price = new_price
        fuel.price_update_time = now
        
        if rule.rule_type == 'same':
            reason_text = '自动定价：与竞争对手价格持平'
        else:
            reason_text = f'自动定价：比竞争对手{rule.rule_type_name}{abs(rule.price_diff):.2f}元'
        
        price_history = PriceHistory(
            fuel_id=fuel.id,
            old_price=old_price,
            new_price=new_price,
            change_time=now,
            change_type='auto',
            reason=reason_text
        )
        db.session.add(price_history)
        
        applied_count += 1
        results.append({
            'fuel_name': fuel.name,
            'status': 'applied',
            'old_price': old_price,
            'new_price': new_price,
            'price_change': round(new_price - old_price, 2)
        })
    
    db.session.commit()
    
    if applied_count > 0:
        flash(f'批量定价已完成，成功调整 {applied_count} 种油品价格，跳过 {skipped_count} 种', 'success')
    else:
        flash(f'所有油品价格无需调整，共跳过 {skipped_count} 种', 'info')
    
    return jsonify({
        'success': True,
        'applied_count': applied_count,
        'skipped_count': skipped_count,
        'results': results
    })

@app.route('/competitor', methods=['GET', 'POST'])
def competitor():
    if request.method == 'POST':
        if 'csv_file' in request.files:
            file = request.files['csv_file']
            if file.filename.endswith('.csv'):
                content = file.read().decode('utf-8-sig')
                reader = csv.DictReader(io.StringIO(content))
                
                for row in reader:
                    date_str = row.get('date') or row.get('日期')
                    try:
                        record_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    except:
                        continue
                    
                    for fuel_code, col_name in [('92', ['92号', '92#', 'gasoline_92']),
                                                ('95', ['95号', '95#', 'gasoline_95']),
                                                ('diesel', ['柴油', '0#', 'diesel'])]:
                        price_val = None
                        for cn in col_name:
                            if cn in row:
                                price_val = row[cn]
                                break
                        
                        if price_val:
                            try:
                                price = float(price_val)
                                fuel = Fuel.query.filter_by(code=fuel_code).first()
                                if fuel:
                                    existing = CompetitorPrice.query.filter_by(
                                        fuel_id=fuel.id, record_date=record_date
                                    ).first()
                                    if existing:
                                        existing.price = price
                                    else:
                                        cp = CompetitorPrice(
                                            fuel_id=fuel.id,
                                            price=price,
                                            record_date=record_date
                                        )
                                        db.session.add(cp)
                            except ValueError:
                                pass
                
                db.session.commit()
                flash('竞争对手价格已导入', 'success')
            else:
                flash('请上传CSV文件', 'error')
        return redirect(url_for('competitor'))
    
    fuels = Fuel.query.all()
    competitor_prices = {}
    
    for fuel in fuels:
        prices = CompetitorPrice.query.filter_by(fuel_id=fuel.id)\
            .order_by(CompetitorPrice.record_date.desc()).limit(30).all()
        competitor_prices[fuel.id] = prices
    
    return render_template('competitor.html',
                         fuels=fuels,
                         competitor_prices=competitor_prices)

@app.route('/sales/report')
def sales_report():
    date_str = request.args.get('date')
    if date_str:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        report_date = datetime.now().date()
    
    fuels = Fuel.query.all()
    daily_sales = get_daily_sales(report_date)
    
    report_data = []
    total_revenue = 0
    total_profit = 0
    total_volume = 0
    
    for fuel in fuels:
        sales = daily_sales.get(fuel.id, {'volume': 0, 'revenue': 0, 'profit': 0})
        avg_cost = get_moving_average_cost(fuel.id)
        current_stock = get_current_stock(fuel.id)
        turnover_days = current_stock / sales['volume'] if sales['volume'] > 0 else 999
        
        report_data.append({
            'fuel_name': fuel.name,
            'volume': round(sales['volume'], 2),
            'revenue': round(sales['revenue'], 2),
            'cost': round(sales['volume'] * avg_cost, 2),
            'profit': round(sales['profit'], 2),
            'avg_cost': round(avg_cost, 3),
            'current_stock': round(current_stock, 2),
            'turnover_days': round(turnover_days, 1)
        })
        
        total_revenue += sales['revenue']
        total_profit += sales['profit']
        total_volume += sales['volume']
    
    return render_template('sales_report.html',
                         report_date=report_date,
                         report_data=report_data,
                         total_revenue=round(total_revenue, 2),
                         total_profit=round(total_profit, 2),
                         total_volume=round(total_volume, 2))

@app.route('/price/history')
def price_history():
    days = int(request.args.get('days', 30))
    fuel_id = request.args.get('fuel_id', type=int)
    change_type = request.args.get('change_type', '')
    
    query = PriceHistory.query
    if fuel_id:
        query = query.filter_by(fuel_id=fuel_id)
    if change_type:
        query = query.filter_by(change_type=change_type)
    
    price_histories = query.order_by(PriceHistory.change_time.desc())\
        .filter(PriceHistory.change_time >= datetime.now() - timedelta(days=days)).all()
    
    fuels = Fuel.query.all()
    
    return render_template('price_history.html',
                         price_histories=price_histories,
                         fuels=fuels,
                         selected_fuel=fuel_id,
                         selected_type=change_type,
                         days=days)

@app.route('/price/rollback/<int:history_id>', methods=['POST'])
def rollback_price(history_id):
    history = PriceHistory.query.get(history_id)
    if not history:
        return jsonify({'success': False, 'message': '调价记录不存在'})
    
    fuel = Fuel.query.get(history.fuel_id)
    if not fuel:
        return jsonify({'success': False, 'message': '油品不存在'})
    
    target_price = history.old_price
    current_price = fuel.current_price
    
    if abs(target_price - current_price) < 0.001:
        return jsonify({
            'success': False, 
            'message': f'{fuel.name} 当前价格已为 ¥{target_price:.2f}，无需回滚'
        })
    
    now = datetime.now()
    old_price = current_price
    
    fuel.current_price = target_price
    fuel.price_update_time = now
    
    rollback_history = PriceHistory(
        fuel_id=history.fuel_id,
        old_price=old_price,
        new_price=target_price,
        change_time=now,
        change_type='manual',
        reason=f'价格回滚：恢复到 {history.change_time.strftime("%Y-%m-%d %H:%M:%S")} 调价前的价格 ¥{target_price:.2f}（原因为：{history.reason or "手动调整"}）'
    )
    db.session.add(rollback_history)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'{fuel.name} 价格已从 ¥{old_price:.2f} 回滚到 ¥{target_price:.2f}',
        'fuel_name': fuel.name,
        'old_price': old_price,
        'new_price': target_price
    })

@app.route('/member/promotion/calculate', methods=['GET'])
def calculate_promo_impact_api():
    discount = request.args.get('discount', type=float)
    use_active = request.args.get('use_active', 'true').lower() == 'true'
    
    if discount is not None and discount <= 0:
        return jsonify({
            'success': False,
            'message': '优惠金额必须大于0'
        })
    
    if discount is not None and discount >= 10:
        return jsonify({
            'success': False,
            'message': '优惠金额不能超过10元'
        })
    
    impact_data = calculate_promotion_impact(discount=discount, use_active_promo=use_active)
    
    return jsonify({
        'success': True,
        'data': impact_data
    })

@app.route('/member/promotion', methods=['GET', 'POST'])
def member_promotion():
    if request.method == 'POST':
        action = request.form.get('action')
        discount = float(request.form.get('discount', 0.5))
        
        if action == 'activate':
            fuels = Fuel.query.all()
            now = datetime.now()
            
            simulate_member_day_sales(discount)
            
            for fuel in fuels:
                mp = MemberPromotion.query.filter_by(fuel_id=fuel.id, is_active=True).first()
                if not mp:
                    original_price = fuel.current_price
                    promo_price = round(original_price - discount, 2)
                    
                    mp = MemberPromotion(
                        fuel_id=fuel.id,
                        discount=discount,
                        original_price=original_price,
                        promo_price=promo_price,
                        start_time=now,
                        is_active=True
                    )
                    db.session.add(mp)
                    
                    old_price = fuel.current_price
                    fuel.current_price = promo_price
                    fuel.price_update_time = now
                    
                    price_history = PriceHistory(
                        fuel_id=fuel.id,
                        old_price=old_price,
                        new_price=promo_price,
                        change_time=now,
                        change_type='auto',
                        reason=f'会员日促销：每升立减{discount:.2f}元'
                    )
                    db.session.add(price_history)
            
            db.session.commit()
            flash('会员日促销已激活，价格已自动调整，已模拟当日销售数据', 'success')
        
        elif action == 'deactivate':
            active_promos = MemberPromotion.query.filter_by(is_active=True).all()
            now = datetime.now()
            for promo in active_promos:
                promo.is_active = False
                promo.end_time = now
                
                fuel = Fuel.query.get(promo.fuel_id)
                old_price = fuel.current_price
                original_price = promo.original_price
                
                fuel.current_price = original_price
                fuel.price_update_time = now
                
                price_history = PriceHistory(
                    fuel_id=promo.fuel_id,
                    old_price=old_price,
                    new_price=original_price,
                    change_time=now,
                    change_type='auto',
                    reason='结束会员日促销，恢复原价'
                )
                db.session.add(price_history)
            
            db.session.commit()
            flash('会员日促销已结束，价格已恢复原价', 'success')
        
        return redirect(url_for('member_promotion'))
    
    fuels = Fuel.query.all()
    active_promos = MemberPromotion.query.filter_by(is_active=True).all()
    promo_map = {p.fuel_id: p for p in active_promos}
    
    impact_data = calculate_promotion_impact()
    
    promo_history = MemberPromotion.query.order_by(MemberPromotion.start_time.desc()).limit(10).all()
    
    return render_template('member_promotion.html',
                         fuels=fuels,
                         promo_map=promo_map,
                         impact_data=impact_data,
                         promo_history=promo_history)

@app.route('/api/stock/<int:fuel_id>')
def api_stock(fuel_id):
    stock = get_current_stock(fuel_id)
    avg_cost = get_moving_average_cost(fuel_id)
    predicted = predict_24h_sales(fuel_id)
    return jsonify({
        'fuel_id': fuel_id,
        'current_stock': stock,
        'avg_cost': avg_cost,
        'predicted_24h_sales': predicted
    })

def init_db():
    with app.app_context():
        db.create_all()
        if Fuel.query.count() == 0:
            fuels = [
                Fuel(code='92', name='92号汽油', tank_capacity=50000, current_price=7.89),
                Fuel(code='95', name='95号汽油', tank_capacity=50000, current_price=8.42),
                Fuel(code='diesel', name='0号柴油', tank_capacity=50000, current_price=7.56)
            ]
            db.session.add_all(fuels)
            
            from datetime import date
            for fuel in fuels:
                db.session.flush()
                for i in range(10):
                    d = date.today() - timedelta(days=9-i)
                    base_price = 7.8 if fuel.code == '92' else 8.4 if fuel.code == '95' else 7.5
                    cp = CompetitorPrice(
                        fuel_id=fuel.id,
                        price=base_price + (i - 5) * 0.05,
                        record_date=d
                    )
                    db.session.add(cp)
            
            rules = [
                PricingRule(fuel_id=1, rule_type='lower', price_diff=0.20, is_active=True),
                PricingRule(fuel_id=2, rule_type='lower', price_diff=0.15, is_active=True),
                PricingRule(fuel_id=3, rule_type='same', price_diff=0, is_active=False)
            ]
            db.session.add_all(rules)
            
            db.session.commit()
            
            initial_intakes = [
                (1, 48000, 7.20),
                (2, 42000, 7.65),
                (3, 45000, 6.90)
            ]
            for fid, vol, cost in initial_intakes:
                intake = IntakeRecord(
                    fuel_id=fid,
                    volume=vol,
                    cost_price=cost,
                    supplier='初始库存',
                    intake_time=datetime.now() - timedelta(days=4)
                )
                db.session.add(intake)
            
            generate_simulated_sales(days=3)
            
            db.session.commit()

if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=5001)
