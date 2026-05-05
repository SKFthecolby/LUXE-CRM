from dataclasses import dataclass


@dataclass
class QuoteInput:
    service_type: str
    bedrooms: int = 0
    bathrooms: int = 0
    living_rooms: int = 0
    additional_rooms: int = 0
    kitchen_size: str = "Medium"
    condition: str = "Average"
    pets: bool = False
    supplies: bool = True
    pantry_org: bool = False


class QuoteEngine:
    def __init__(self, db):
        self.db = db

    def _cfg(self, key, default):
        try:
            return float(self.db.setting(key))
        except Exception:
            return float(default)

    def _base_settings(self):
        return {
            "base_service_low": self._cfg("quote_base_service_low", 40),
            "base_service_high": self._cfg("quote_base_service_high", 55),
            "bedroom_low": self._cfg("quote_bedroom_low", 28),
            "bedroom_high": self._cfg("quote_bedroom_high", 40),
            "bathroom_low": self._cfg("quote_bathroom_low", 35),
            "bathroom_high": self._cfg("quote_bathroom_high", 50),
            "living_low": self._cfg("quote_living_low", 25),
            "living_high": self._cfg("quote_living_high", 38),
            "additional_low": self._cfg("quote_additional_low", 21.5),
            "additional_high": self._cfg("quote_additional_high", 31.25),
            "kitchen_small_low": self._cfg("quote_kitchen_small_low", 26),
            "kitchen_small_high": self._cfg("quote_kitchen_small_high", 36),
            "kitchen_medium_low": self._cfg("quote_kitchen_medium_low", 32),
            "kitchen_medium_high": self._cfg("quote_kitchen_medium_high", 45),
            "kitchen_large_low": self._cfg("quote_kitchen_large_low", 42),
            "kitchen_large_high": self._cfg("quote_kitchen_large_high", 58),
            "deep_multiplier_low": self._cfg("quote_deep_multiplier_low", 1.18),
            "deep_multiplier_high": self._cfg("quote_deep_multiplier_high", 1.35),
            "moveout_multiplier_low": self._cfg("quote_moveout_multiplier_low", 1.35),
            "moveout_multiplier_high": self._cfg("quote_moveout_multiplier_high", 1.55),
            "condition_clean": self._cfg("quote_condition_clean", 0.95),
            "condition_average": self._cfg("quote_condition_average", 1.00),
            "condition_extra": self._cfg("quote_condition_extra", 1.20),
            "pet_flat_low": self._cfg("quote_pet_flat_low", 15),
            "pet_flat_high": self._cfg("quote_pet_flat_high", 30),
            "supplies_low": self._cfg("quote_supplies_low", 10),
            "supplies_high": self._cfg("quote_supplies_high", 18),
            "pantry_org_low": self._cfg("quote_pantry_org_low", 35),
            "pantry_org_high": self._cfg("quote_pantry_org_high", 75),
        }

    def estimate(self, q: QuoteInput):
        s = self._base_settings()

        k_low = {
            "Small": s["kitchen_small_low"],
            "Medium": s["kitchen_medium_low"],
            "Large": s["kitchen_large_low"],
        }[q.kitchen_size]

        k_high = {
            "Small": s["kitchen_small_high"],
            "Medium": s["kitchen_medium_high"],
            "Large": s["kitchen_large_high"],
        }[q.kitchen_size]

        low = (
            s["base_service_low"]
            + q.bedrooms * s["bedroom_low"]
            + q.bathrooms * s["bathroom_low"]
            + q.living_rooms * s["living_low"]
            + q.additional_rooms * s["additional_low"]
            + k_low
        )

        high = (
            s["base_service_high"]
            + q.bedrooms * s["bedroom_high"]
            + q.bathrooms * s["bathroom_high"]
            + q.living_rooms * s["living_high"]
            + q.additional_rooms * s["additional_high"]
            + k_high
        )

        if q.service_type == "Deep Clean":
            low *= s["deep_multiplier_low"]
            high *= s["deep_multiplier_high"]
        elif q.service_type == "Move-Out":
            low *= s["moveout_multiplier_low"]
            high *= s["moveout_multiplier_high"]

        cond_mult = {
            "Clean": s["condition_clean"],
            "Average": s["condition_average"],
            "Needs Extra Attention": s["condition_extra"],
        }[q.condition]

        low *= cond_mult
        high *= cond_mult

        if q.pets:
            low += s["pet_flat_low"]
            high += s["pet_flat_high"]

        if q.supplies:
            low += s["supplies_low"]
            high += s["supplies_high"]

        if q.pantry_org:
            low += s["pantry_org_low"]
            high += s["pantry_org_high"]

        recommended = round((low + high) / 2.0, 2)

        return {
            "low_estimate": round(low, 2),
            "high_estimate": round(high, 2),
            "recommended": recommended,
        }

    def hours(self, q: QuoteInput):
        base_low = 2.5
        base_high = 4.0

        size_add = (
            max(q.bedrooms - 2, 0) * 0.4
            + max(q.bathrooms - 2, 0) * 0.35
            + q.additional_rooms * 0.25
            + q.living_rooms * 0.2
        )

        low = base_low + size_add
        high = base_high + size_add

        if q.service_type == "Deep Clean":
            low += 1.0
            high += 2.0
        elif q.service_type == "Move-Out":
            low += 2.0
            high += 3.0

        if q.condition == "Needs Extra Attention":
            low += 0.75
            high += 1.5
        elif q.condition == "Clean":
            low -= 0.25
            high -= 0.25

        if q.pets:
            low += 0.25
            high += 0.5

        if q.pantry_org:
            low += 0.5
            high += 1.0

        return {
            "low_hours": round(max(low, 1.0), 2),
            "high_hours": round(max(high, 1.5), 2),
        }