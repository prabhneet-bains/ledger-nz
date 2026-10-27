export type Account = {
  account_id: string;
  account_name: string;
  account_type: string;
  tax_rate: string | number;
  business_claim_percentage: string | number;
};

export type Transaction = {
  transaction_id: string;
  date: string;
  account_id: string | null;
  payee?: string;
  description: string;
  gross_amount: string | number;
  gst_amount: string | number;
  net_amount: string | number;
  business_claim_percentage?: string | number;
  is_internal_transfer?: boolean;
  source: string;
  status: string;
};

export type DashboardSummary = {
  financial_year: { start: string; end: string };
  pending_review: number;
  pnl: {
    total_income: string;
    total_expense: string;
    net_profit: string;
    private_excluded?: string;
    drawings?: string;
    funds_introduced?: string;
    transfers_excluded?: number;
    uncoded_count?: number;
    uncoded_gross?: string;
    lines: { account_name: string; account_type: string; net_amount: string }[];
    income_lines?: { account_name: string; account_type: string; net_amount: string }[];
    expense_lines?: { account_name: string; account_type: string; net_amount: string }[];
    depreciation?: {
      total: string;
      lines: {
        asset_name: string;
        depreciation_method: string;
        depreciation_rate: string;
        depreciation_claim: string;
        business_use_percentage: string;
        business_use_source: string;
        months: number;
        adjusted_tax_value: string;
        low_value_writeoff: boolean;
      }[];
    };
    income_tax?: {
      taxable_profit: string;
      income_tax: string;
      profit_after_tax: string;
      rates_from: string;
      bands: { label: string; income: string; tax: string }[];
    };
  };
  gst: { output_gst: string; input_gst: string; gst_to_pay: string; start: string; end: string };
  tax_history: {
    record_id: string;
    period_type: string;
    start_date: string;
    end_date: string;
    total_income: string;
    tax_paid: string;
  }[];
};
