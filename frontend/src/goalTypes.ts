export type Goal = {
  id: string; name: string; metric_type: "monthly_spend";
  period_type: "calendar_month"; scope_kind: "category" | "subcategory";
  category_id: string; category_name: string; threshold_amount: string;
  currency: string; timezone: string; status: "active" | "paused";
  rule_version: number;
};

export type GoalEvidence = {
  transaction_id: string; posted_date: string; merchant: string;
  amount: string; direction: "debit" | "credit";
  pending: boolean; category_id: string | null;
};

export type GoalEvaluation = {
  goal_id: string; goal: Goal; month: string;
  period_start: string; period_end: string; evaluated_at: string;
  threshold_amount: string; currency: string;
  posted_gross: string; posted_credits: string; posted_spend: string;
  pending_net: string; projected_spend: string;
  remaining: string; over_amount: string; progress_percent: string;
  evidence: GoalEvidence[];
  exclusions: { unknown_currency: number; other_currency: number };
  caveats: string[];
};

export type GoalCategory = {
  category_id: string; display_name: string;
  subcategories: { category_id: string; display_name: string }[];
};
