from pydantic import BaseModel, ConfigDict, Field


class ExplanationModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Evidence(ExplanationModel):
    rule_id: str
    inputs: dict[str, float]
    observation: str
    derived: bool = False


class Component(ExplanationModel):
    state: str
    headline: str
    points: list[str]
    evidence: list[Evidence]
    missing_inputs: list[str] = Field(default_factory=list)


class Summary(ExplanationModel):
    headline: str
    text: str


class Explanation(ExplanationModel):
    rules_version: str = 'analysis-explanation-v1'
    scope: str = 'Descriptive observations from the completed-candle analysis snapshot; not strategy scoring or investment advice.'
    analysis_as_of: str | None
    analysis_last_bar: str | None
    market_status: str
    trend: Component
    momentum: Component
    volume: Component
    risk: Component
    summary: Summary
    warnings: list[str]
