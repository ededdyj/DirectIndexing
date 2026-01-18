from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional
from typing_extensions import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Term(str, Enum):
    SHORT = "ST"
    LONG = "LT"
    UNKNOWN = "UNKNOWN"


class Holding(BaseModel):
    symbol: str
    qty: float = Field(..., gt=0)
    price: Optional[float] = Field(default=None, gt=0)
    market_value: Optional[float] = Field(default=None, ge=0)
    cost_basis_total: Optional[float] = Field(default=None, ge=0)
    is_cash_equivalent: bool = Field(default=False)

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, v: str) -> str:
        return v.upper().strip()


class Lot(BaseModel):
    lot_id: str
    symbol: str
    acquired_date: date
    qty: float = Field(..., gt=0)
    basis_total: float = Field(..., ge=0)
    covered: Optional[bool] = None
    current_value: Optional[float] = Field(default=None, ge=0)
    current_price: Optional[float] = Field(default=None, ge=0)

    term: Term = Field(default=Term.SHORT)

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, v: str) -> str:
        return v.upper().strip()

    @model_validator(mode="after")
    def derive_term(self) -> "Lot":
        cutoff = date.today().toordinal() - 365
        if self.acquired_date.toordinal() <= cutoff:
            self.term = Term.LONG
        else:
            self.term = Term.SHORT
        return self

    @property
    def basis_per_share(self) -> float:
        return self.basis_total / self.qty if self.qty else 0.0


class TLHCandidate(BaseModel):
    symbol: str
    lot_id: str
    qty: float
    basis_total: float
    current_value: float
    unrealized_pl: float
    pl_pct: float
    term: Term
    notes: List[str] = Field(default_factory=list)


class OrderChecklistRow(BaseModel):
    symbol: str
    side: str
    qty: float
    limit_price: Optional[float] = None
    rationale: Optional[str] = None


class Proposal(BaseModel):
    sells: List[OrderChecklistRow]
    buys: List[OrderChecklistRow]
    expected_realized_loss: float
    notes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReplacementBasket(BaseModel):
    symbol: str
    weight: float


class Trade(BaseModel):
    symbol: str
    side: str
    trade_date: date
    qty: float


class AccountSummary(BaseModel):
    account: str
    net_account_value: Optional[float] = None
    total_gain_amount: Optional[float] = None
    total_gain_pct: Optional[float] = None
    days_gain_amount: Optional[float] = None
    days_gain_pct: Optional[float] = None
    available_for_withdrawal: Optional[float] = None
    cash_purchasing_power: Optional[float] = None


class PortfolioDownloadParseResult(BaseModel):
    holdings: List[Holding]
    lots: List[Lot]
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    detected_format: str = "E*TRADE Portfolio Download (PositionsSimple)"
    positions_header: List[str] = Field(default_factory=list)
    account_summary: Optional[AccountSummary] = None


class RealizedGainLossRow(BaseModel):
    symbol: str
    quantity: float = Field(..., gt=0)
    date_acquired: Optional[date] = None
    date_sold: date
    proceeds: Optional[float] = None
    cost_basis: Optional[float] = None
    realized_gain_loss: float
    term: Term = Term.UNKNOWN
    wash_sale_disallowed: Optional[float] = None
    source_row_id: Optional[str] = None

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, v: str) -> str:
        return v.upper().strip()


class RealizedSummary(BaseModel):
    ytd_realized_st: float = 0.0
    ytd_realized_lt: float = 0.0
    ytd_realized_unknown: float = 0.0
    ytd_realized_total: float = 0.0
    ytd_wash_sale_disallowed_total: float = 0.0
    rows_count: int = 0
    warnings: List[str] = Field(default_factory=list)


class GainsLossesParseResult(BaseModel):
    rows: List[RealizedGainLossRow]
    warnings: List[str] = Field(default_factory=list)
    detected_format: str = "E*TRADE Gains & Losses"
    header: List[str] = Field(default_factory=list)


class SellLotRecommendation(BaseModel):
    symbol: str
    lot_id: str
    acquired_date: Optional[date]
    qty: float
    price: float
    proceeds: float
    basis: float
    gain_loss: float
    term: Term
    estimated_tax: float
    rationale: List[str] = Field(default_factory=list)


class WithdrawalProposal(BaseModel):
    requested_amount: float
    buffer_amount: float
    cash_available: float
    amount_needed_from_sales: float
    total_expected_proceeds: float
    estimated_realized_st: float
    estimated_realized_lt: float
    estimated_tax_cost: float
    sells: List[SellLotRecommendation]
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    drift_metrics: List[str] = Field(default_factory=list)


class StrategySpec(BaseModel):
    index_name: Literal["sp500", "total_us", "nasdaq100"]
    holdings_count: int = Field(..., ge=1)
    max_single_name_weight: float = Field(..., gt=0, le=1)
    screens: Dict[str, bool] = Field(default_factory=dict)
    excluded_symbols: List[str] = Field(default_factory=list)
    include_cash_equivalents: bool = False

    @field_validator("excluded_symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, v):
        if not v:
            return []
        return [str(sym).upper().strip() for sym in v if str(sym).strip()]


class TargetBasketRow(BaseModel):
    symbol: str
    target_weight: float
    sector: Optional[str] = None
    source_index: str

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, v: str) -> str:
        return v.upper().strip()


class TaxRateInput(BaseModel):
    short_term: float = 0.32
    long_term: float = 0.15
    state: float = 0.05


class StrategyAllocationRequest(BaseModel):
    allocation_amount: float
    cash_buffer_amount: Optional[float] = None
    cash_buffer_pct: Optional[float] = None
    manual_cash_available: float = 0.0
    use_cash_equivalents_first: bool = True
    excluded_from_selling: List[str] = Field(default_factory=list)
    liquidation_goal: Literal["min_tax", "balanced", "min_drift"] = "min_tax"
    tax_rates: Optional[TaxRateInput] = None
    exclude_missing_dates: bool = True

    @field_validator("excluded_from_selling", mode="before")
    @classmethod
    def normalize_symbols(cls, v):
        if not v:
            return []
        return [str(sym).upper().strip() for sym in v if str(sym).strip()]


class BuyTargetRow(BaseModel):
    symbol: str
    target_weight: float
    target_dollars: float
    price: Optional[float] = None
    est_shares: Optional[float] = None

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, v: str) -> str:
        return v.upper().strip()


class EstimatedTaxImpact(BaseModel):
    st_realized: float = 0.0
    lt_realized: float = 0.0
    st_tax: float = 0.0
    lt_tax: float = 0.0
    total_tax: float = 0.0
    notes: List[str] = Field(default_factory=list)


class TransitionPlan(BaseModel):
    allocation_amount: float
    buffer_amount: float
    cash_available: float
    cash_used: float
    cash_needed_from_sales: float
    sells: List[SellLotRecommendation]
    estimated_tax: EstimatedTaxImpact
    buys: List[BuyTargetRow]
    warnings: List[str] = Field(default_factory=list)
    drift_metrics: List[str] = Field(default_factory=list)
    rationale_summary: str = ""


class ManageActionSettings(BaseModel):
    mode: Literal["tlh", "rebalance", "combined"] = "tlh"
    drift_tolerance_pct: float = 0.01
    turnover_cap_pct: float = 0.05
    tax_goal: Literal["min_tax", "balanced", "min_drift"] = "min_tax"
    tlh_candidate_limit: int = 5


class DriftEntry(BaseModel):
    symbol: str
    target_weight: float
    actual_weight: float
    drift: float
    sector: Optional[str] = None


class DriftSummary(BaseModel):
    sleeve_value: float
    max_abs_drift: float
    total_abs_drift: float
    overweights: List[DriftEntry] = Field(default_factory=list)
    underweights: List[DriftEntry] = Field(default_factory=list)
    sector_drift: List[DriftEntry] = Field(default_factory=list)


class StrategyManagePlan(BaseModel):
    drift_summary: DriftSummary
    tlh_sells: List[SellLotRecommendation] = Field(default_factory=list)
    rebalance_sells: List[SellLotRecommendation] = Field(default_factory=list)
    buy_targets: List[BuyTargetRow] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
