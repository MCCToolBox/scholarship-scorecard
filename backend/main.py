
import os, hmac, hashlib, json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import List, Union

with open(os.path.join(os.path.dirname(__file__), "config.json"), "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

SECRET = os.environ.get("SCORING_HMAC_SECRET", "change-me")

app = FastAPI(title="Scholarship Application API", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CONFIG.get("allowed_origins", ["*"]),
    allow_credentials=False,
    allow_methods=["GET","POST"],
    allow_headers=["content-type","authorization"],
)

class FactorInput(BaseModel):
    key: str
    value: Union[str, float, int]

class ScoreRequest(BaseModel):
    applicant: str = Field(default="")
    factors: List[FactorInput]

    @validator("factors")
    def keys_known(cls, v):
        allowed = {f["key"] for f in CONFIG["factors"]}
        for item in v:
            if item.key not in allowed:
                raise ValueError(f"Unknown factor key: {item.key}")
        return v

def map_to_numeric(fconf, raw):
    if fconf.get("type","select") == "select":
        mapping = fconf.get("map", {})
        return float(mapping.get(str(raw), 0.0))
    try:
        return float(raw)
    except:
        return 0.0

def decide(ix: float) -> str:
    t = CONFIG["decision_thresholds"]
    if ix < t["decline_max"]:
        return "Decline"
    if ix < t["partial_max"]:
        return "Partial"
    return "Full"

@app.get("/api/config")
def get_config():
    # Expose only labels and options
    return {
        "version": CONFIG["version"],
        "factors": [{k:v for k,v in f.items() if k in ("key","label","type","options")} for f in CONFIG["factors"]],
        "ui": CONFIG.get("ui", {}),
    }

@app.post("/api/score")
def score(req: ScoreRequest):
    # Build context and compute S
    S = 0.0
    for f in CONFIG["factors"]:
        sel = next((x.value for x in req.factors if x.key == f["key"]), None)
        s = map_to_numeric(f, sel)
        S += float(f["weight"]) * s

    # Cross-factor bonuses on raw selections
    raw = {x.key: x.value for x in req.factors}
    bonus_sum = 0.0
    for r in CONFIG["rules"]:
        try:
            if eval(r["trigger"], {"__builtins__": {}}, {"raw": raw}):
                bonus_sum += float(r["bonus"])
        except Exception:
            pass
    capped = min(bonus_sum, float(CONFIG.get("cap",0.10)))
    index = (S + capped) * 100.0
    decision = decide(index)

    result = {"decision": decision, "index": round(index,1), "version": CONFIG["version"]}
    msg = json.dumps(result, separators=(",",":"), sort_keys=True).encode()
    sig = hmac.new(os.environ.get("SCORING_HMAC_SECRET","change-me").encode(), msg, hashlib.sha256).hexdigest()
    result["signature"] = sig
    return result
