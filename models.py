from datetime import datetime
from database import db

class Fuel(db.Model):
    __tablename__ = 'fuels'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(50), nullable=False)
    tank_capacity = db.Column(db.Float, default=50000)
    current_price = db.Column(db.Float, nullable=False)
    price_update_time = db.Column(db.DateTime, default=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    intake_records = db.relationship('IntakeRecord', backref='fuel', lazy='dynamic')
    sales_records = db.relationship('SalesRecord', backref='fuel', lazy='dynamic')
    price_histories = db.relationship('PriceHistory', backref='fuel', lazy='dynamic')
    competitor_prices = db.relationship('CompetitorPrice', backref='fuel', lazy='dynamic')
    member_promotions = db.relationship('MemberPromotion', backref='fuel', lazy='dynamic')
    
    def __repr__(self):
        return f'<Fuel {self.name}>'

class IntakeRecord(db.Model):
    __tablename__ = 'intake_records'
    
    id = db.Column(db.Integer, primary_key=True)
    fuel_id = db.Column(db.Integer, db.ForeignKey('fuels.id'), nullable=False)
    volume = db.Column(db.Float, nullable=False)
    cost_price = db.Column(db.Float, nullable=False)
    total_cost = db.Column(db.Float)
    supplier = db.Column(db.String(100))
    truck_no = db.Column(db.String(50))
    intake_time = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.volume and self.cost_price and not self.total_cost:
            self.total_cost = self.volume * self.cost_price

class SalesRecord(db.Model):
    __tablename__ = 'sales_records'
    
    id = db.Column(db.Integer, primary_key=True)
    fuel_id = db.Column(db.Integer, db.ForeignKey('fuels.id'), nullable=False)
    volume = db.Column(db.Float, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    total_revenue = db.Column(db.Float)
    cost_price = db.Column(db.Float)
    total_cost = db.Column(db.Float)
    profit = db.Column(db.Float)
    is_member = db.Column(db.Boolean, default=False)
    member_discount = db.Column(db.Float, default=0)
    sale_time = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.volume and self.unit_price and not self.total_revenue:
            self.total_revenue = self.volume * self.unit_price
        if self.volume and self.cost_price and not self.total_cost:
            self.total_cost = self.volume * self.cost_price
        if self.total_revenue and self.total_cost and not self.profit:
            self.profit = self.total_revenue - self.total_cost

class PriceHistory(db.Model):
    __tablename__ = 'price_histories'
    
    id = db.Column(db.Integer, primary_key=True)
    fuel_id = db.Column(db.Integer, db.ForeignKey('fuels.id'), nullable=False)
    old_price = db.Column(db.Float, nullable=False)
    new_price = db.Column(db.Float, nullable=False)
    change_time = db.Column(db.DateTime, nullable=False)
    change_type = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.now)

class CompetitorPrice(db.Model):
    __tablename__ = 'competitor_prices'
    
    id = db.Column(db.Integer, primary_key=True)
    fuel_id = db.Column(db.Integer, db.ForeignKey('fuels.id'), nullable=False)
    price = db.Column(db.Float, nullable=False)
    record_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    __table_args__ = (
        db.UniqueConstraint('fuel_id', 'record_date', name='_fuel_date_uc'),
    )

class PricingRule(db.Model):
    __tablename__ = 'pricing_rules'
    
    id = db.Column(db.Integer, primary_key=True)
    fuel_id = db.Column(db.Integer, db.ForeignKey('fuels.id'), nullable=False)
    rule_type = db.Column(db.String(20), nullable=False)
    price_diff = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    @property
    def rule_type_name(self):
        type_map = {
            'lower': '低',
            'higher': '高',
            'same': '持平'
        }
        return type_map.get(self.rule_type, '未知')

class MemberPromotion(db.Model):
    __tablename__ = 'member_promotions'
    
    id = db.Column(db.Integer, primary_key=True)
    fuel_id = db.Column(db.Integer, db.ForeignKey('fuels.id'), nullable=False)
    discount = db.Column(db.Float, nullable=False)
    original_price = db.Column(db.Float, nullable=False)
    promo_price = db.Column(db.Float, nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
