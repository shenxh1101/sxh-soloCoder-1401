from datetime import datetime, timedelta, date
from models import *
from database import db
import random

HOURLY_SALES_PROFILE = {
    0: 0.01, 1: 0.005, 2: 0.003, 3: 0.002, 4: 0.002, 5: 0.005,
    6: 0.02, 7: 0.05, 8: 0.08, 9: 0.07, 10: 0.06, 11: 0.065,
    12: 0.07, 13: 0.06, 14: 0.055, 15: 0.06, 16: 0.07, 17: 0.09,
    18: 0.08, 19: 0.06, 20: 0.04, 21: 0.025, 22: 0.015, 23: 0.01
}

def get_current_stock(fuel_id):
    intakes = IntakeRecord.query.filter_by(fuel_id=fuel_id).all()
    total_intake = sum(r.volume for r in intakes)
    
    sales = SalesRecord.query.filter_by(fuel_id=fuel_id).all()
    total_sales = sum(r.volume for r in sales)
    
    return total_intake - total_sales

def get_moving_average_cost(fuel_id):
    intakes = IntakeRecord.query.filter_by(fuel_id=fuel_id)\
        .order_by(IntakeRecord.intake_time.asc()).all()
    
    if not intakes:
        return 0
    
    total_volume = 0
    total_cost = 0
    
    for intake in intakes:
        new_total_volume = total_volume + intake.volume
        new_total_cost = total_cost + (intake.volume * intake.cost_price)
        total_volume = new_total_volume
        total_cost = new_total_cost
    
    if total_volume == 0:
        return 0
    
    return total_cost / total_volume

def get_latest_competitor_price(fuel_id):
    latest = CompetitorPrice.query.filter_by(fuel_id=fuel_id)\
        .order_by(CompetitorPrice.record_date.desc()).first()
    return latest.price if latest else None

def predict_24h_sales(fuel_id):
    seven_days_ago = datetime.now() - timedelta(days=7)
    sales = SalesRecord.query.filter(
        SalesRecord.fuel_id == fuel_id,
        SalesRecord.sale_time >= seven_days_ago
    ).all()
    
    if not sales:
        base_daily = {
            1: 8000,
            2: 5000,
            3: 6000
        }.get(fuel_id, 5000)
        return base_daily
    
    total_volume = sum(s.volume for s in sales)
    daily_avg = total_volume / 7
    
    day_factor = 1.0
    today = datetime.now().weekday()
    if today >= 5:
        day_factor = 1.15
    
    return daily_avg * day_factor

def get_daily_sales(report_date):
    if isinstance(report_date, datetime):
        report_date = report_date.date()
    
    start = datetime.combine(report_date, datetime.min.time())
    end = datetime.combine(report_date + timedelta(days=1), datetime.min.time())
    
    sales = SalesRecord.query.filter(
        SalesRecord.sale_time >= start,
        SalesRecord.sale_time < end
    ).all()
    
    result = {}
    for sale in sales:
        if sale.fuel_id not in result:
            result[sale.fuel_id] = {'volume': 0, 'revenue': 0, 'profit': 0, 'count': 0}
        result[sale.fuel_id]['volume'] += sale.volume
        result[sale.fuel_id]['revenue'] += sale.total_revenue
        result[sale.fuel_id]['profit'] += sale.profit
        result[sale.fuel_id]['count'] += 1
    
    return result

def generate_simulated_sales(days=7):
    fuels = Fuel.query.all()
    
    for day_offset in range(days):
        sale_date = date.today() - timedelta(days=days - day_offset)
        is_weekend = sale_date.weekday() >= 5
        weekend_factor = 1.2 if is_weekend else 1.0
        
        for fuel in fuels:
            base_daily = {
                '92': 8000,
                '95': 5000,
                'diesel': 6000
            }.get(fuel.code, 5000)
            
            daily_volume = base_daily * weekend_factor * random.uniform(0.9, 1.1)
            avg_cost = get_moving_average_cost(fuel.id) or 7.0
            price = fuel.current_price
            
            num_transactions = random.randint(80, 150)
            
            for _ in range(num_transactions):
                hour = random.choices(
                    list(HOURLY_SALES_PROFILE.keys()),
                    weights=list(HOURLY_SALES_PROFILE.values()),
                    k=1
                )[0]
                
                volume = (daily_volume / num_transactions) * random.uniform(0.5, 1.5)
                volume = round(volume, 2)
                
                sale_time = datetime.combine(sale_date, datetime.min.time()) + timedelta(
                    hours=hour,
                    minutes=random.randint(0, 59)
                )
                
                is_member = random.random() < 0.3
                member_discount = 0
                
                sale = SalesRecord(
                    fuel_id=fuel.id,
                    volume=volume,
                    unit_price=price,
                    cost_price=avg_cost,
                    total_revenue=volume * price,
                    total_cost=volume * avg_cost,
                    profit=volume * (price - avg_cost),
                    is_member=is_member,
                    member_discount=member_discount,
                    sale_time=sale_time
                )
                db.session.add(sale)

def simulate_member_day_sales(discount=0.5):
    fuels = Fuel.query.all()
    today = date.today()
    
    for fuel in fuels:
        current_stock = get_current_stock(fuel.id)
        if current_stock <= 0:
            continue
        
        base_daily = {
            '92': 12000,
            '95': 7000,
            'diesel': 8000
        }.get(fuel.code, 5000)
        
        promo_volume = min(base_daily * random.uniform(1.3, 1.6), current_stock * 0.8)
        avg_cost = get_moving_average_cost(fuel.id)
        original_price = fuel.current_price
        promo_price = original_price - discount
        
        num_transactions = random.randint(150, 250)
        
        for _ in range(num_transactions):
            hour = random.choices(
                list(HOURLY_SALES_PROFILE.keys()),
                weights=list(HOURLY_SALES_PROFILE.values()),
                k=1
            )[0]
            
            volume = (promo_volume / num_transactions) * random.uniform(0.5, 1.5)
            volume = round(min(volume, current_stock), 2)
            
            if volume <= 0:
                continue
            
            sale_time = datetime.combine(today, datetime.min.time()) + timedelta(
                hours=hour,
                minutes=random.randint(0, 59)
            )
            
            sale = SalesRecord(
                fuel_id=fuel.id,
                volume=volume,
                unit_price=promo_price,
                cost_price=avg_cost,
                total_revenue=volume * promo_price,
                total_cost=volume * avg_cost,
                profit=volume * (promo_price - avg_cost),
                is_member=True,
                member_discount=discount,
                sale_time=sale_time
            )
            db.session.add(sale)
            current_stock -= volume

def calculate_promotion_impact():
    today = date.today()
    fuels = Fuel.query.all()
    
    impact_data = []
    total_normal_profit = 0
    total_promo_profit = 0
    total_normal_revenue = 0
    total_promo_revenue = 0
    
    for fuel in fuels:
        base_daily = {
            '92': 8000,
            '95': 5000,
            'diesel': 6000
        }.get(fuel.code, 5000)
        
        avg_cost = get_moving_average_cost(fuel.id)
        original_price = fuel.current_price
        
        normal_volume = base_daily
        normal_revenue = normal_volume * original_price
        normal_profit = normal_volume * (original_price - avg_cost)
        
        promo_discount = 0.5
        promo_price = original_price - promo_discount
        promo_volume = base_daily * 1.4
        promo_revenue = promo_volume * promo_price
        promo_profit = promo_volume * (promo_price - avg_cost)
        
        profit_diff = promo_profit - normal_profit
        revenue_diff = promo_revenue - normal_revenue
        volume_increase = ((promo_volume - normal_volume) / normal_volume) * 100
        
        impact_data.append({
            'fuel_name': fuel.name,
            'original_price': round(original_price, 2),
            'promo_price': round(promo_price, 2),
            'discount': round(promo_discount, 2),
            'normal_volume': round(normal_volume, 0),
            'promo_volume': round(promo_volume, 0),
            'volume_increase': round(volume_increase, 1),
            'normal_revenue': round(normal_revenue, 2),
            'promo_revenue': round(promo_revenue, 2),
            'revenue_diff': round(revenue_diff, 2),
            'normal_profit': round(normal_profit, 2),
            'promo_profit': round(promo_profit, 2),
            'profit_diff': round(profit_diff, 2)
        })
        
        total_normal_profit += normal_profit
        total_promo_profit += promo_profit
        total_normal_revenue += normal_revenue
        total_promo_revenue += promo_revenue
    
    return {
        'items': impact_data,
        'total_normal_profit': round(total_normal_profit, 2),
        'total_promo_profit': round(total_promo_profit, 2),
        'total_profit_diff': round(total_promo_profit - total_normal_profit, 2),
        'total_normal_revenue': round(total_normal_revenue, 2),
        'total_promo_revenue': round(total_promo_revenue, 2),
        'total_revenue_diff': round(total_promo_revenue - total_normal_revenue, 2)
    }
