"""
Risk management — position sizing, drawdown limits, circuit breakers.
"""

from config import settings
from utils.logger import get_logger
from utils.performance import PerformanceTracker

log = get_logger("risk")


class RiskManager:
    """Controls position sizing and enforces risk limits."""

    def __init__(self, tracker: PerformanceTracker):
        self.tracker = tracker
        self._halted = False
        self._halt_reason = ""

    def can_open_trade(self) -> tuple[bool, str]:
        """Check if a new trade is allowed.
        
        Returns:
            (allowed: bool, reason: str)
        """
        # Check halt state
        if self._halted:
            return False, f"Trading halted: {self._halt_reason}"

        # Max concurrent positions
        # (strategy tracks this, but double-check)

        # Consecutive losses
        if self.tracker.consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            self._halted = True
            self._halt_reason = (
                f"{self.tracker.consecutive_losses} consecutive losses"
            )
            log.risk(f"HALTED: {self._halt_reason}")
            return False, self._halt_reason

        # Daily drawdown
        dd = self.tracker.daily_drawdown_pct
        if dd >= settings.MAX_DAILY_DRAWDOWN:
            self._halted = True
            self._halt_reason = f"Daily drawdown {dd:.2%} >= {settings.MAX_DAILY_DRAWDOWN:.2%}"
            log.risk(f"HALTED: {self._halt_reason}")
            return False, self._halt_reason

        return True, "OK"

    def calculate_position_size(self, balance: float, entry_price: float,
                                 stop_loss: float) -> float:
        """Calculate position size based on risk per trade.
        
        Uses: quantity = (balance * risk%) / |entry - SL|
        Reduces size after consecutive losses.
        
        Args:
            balance: Current account balance in USDT
            entry_price: Planned entry price
            stop_loss: Planned stop loss price
            
        Returns:
            Position size in base asset units
        """
        risk_pct = settings.RISK_PER_TRADE

        # Adaptive sizing: halve after N consecutive losses
        if self.tracker.consecutive_losses >= settings.REDUCE_SIZE_AFTER_LOSSES:
            risk_pct *= 0.5
            log.risk(
                f"Reduced risk to {risk_pct:.4%} after {self.tracker.consecutive_losses} losses"
            )

        risk_amount = balance * risk_pct
        sl_distance = abs(entry_price - stop_loss)

        if sl_distance == 0:
            log.risk("SL distance is zero, cannot size position")
            return 0.0

        quantity = risk_amount / sl_distance

        # Sanity: cap at 50% of balance worth
        max_qty = (balance * 0.5) / entry_price
        quantity = min(quantity, max_qty)

        log.info(
            f"Position size: {quantity:.6f} | Risk: {risk_amount:.2f} USDT | SL dist: {sl_distance:.2f}"
        )
        return quantity

    def record_result(self, pnl: float):
        """Delegate to tracker — called by order manager on fill."""
        # Tracker handles win/loss counting internally
        pass

    def reset_daily(self):
        """Reset daily state — call at session open."""
        self._halted = False
        self._halt_reason = ""
        self.tracker.reset_daily()
        log.info("Daily risk counters reset")

    def force_resume(self):
        """Manual override to resume after halt."""
        self._halted = False
        self._halt_reason = ""
        log.risk("Trading manually resumed")

    @property
    def is_halted(self) -> bool:
        return self._halted
