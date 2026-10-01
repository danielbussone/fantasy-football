export type Proj = {
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  mean: number;
  sim?: Record<string, number>;
  usage?: {
    source?: string;
    pass_att?: number | null;
    carries?: number | null;
    targets?: number | null;
    receptions?: number | null;
    fg_att?: number | null;
    has_3g?: boolean;
    season_carries?: number | null;
    season_targets?: number | null;
    g3_carries?: number | null;
    g3_targets?: number | null;
    ypc?: number | null;
    ypt?: number | null;
  };
  explain?: { rows: { cat: string; input: string; pts: number | null; note?: string }[]; lines: string[]; approx_pts?: number };
  source?: string;
};

export type Injury = {
  designation: string;
  note: string;
  source: string;
  as_of: string;
  out?: boolean;
} | null;

export type RosterNote = {
  text: string;
  source: string;
  as_of?: string;
} | null;

export type GradeFlag = "next_up" | "buy_low";

// Usage grade for a WR/TE/RB, from nflverse through the last completed week.
export type Grade = {
  role: number; // 0–100 percentile of the position's usage stat
  usage_stat: "wopr" | "opp_share" | "epa";
  usage: number | null;
  snap_pct: number | null;
  rank: number; // position rank by projected points/game
  of: number;
  par_ppg: number; // predicted points/game, pedigree bump included
  par: number; // points above the best free agent, rest of season
  exp_games: number;
  team_games_left: number;
  status: string; // Out / Doubtful / Questionable / ""
  games: number;
  ppg: number;
  years: number | null;
  round: number;
  bump: number;
  flags: GradeFlag[];
  waiver_tier: boolean;
  vac_pos: number;
} | null;

// DST: next opponent's Vegas implied total, lower is a better week. K: own implied total.
export type Stream = { opp: string; opp_total: number; own_total: number | null; rank: number; of: number; score: number } | null;
export type KickStream = { implied: number; dome: boolean; rank: number; of: number; score: number } | null;

export type TrackerCard = {
  player: string;
  team: string;
  pos: string;
  usage_stat: "wopr" | "opp_share" | "epa";
  usage: number | null;
  snap_pct: number | null;
  ppg: number;
  years: number | null;
  round: number;
  flags: GradeFlag[];
  par: number;
  pred_ppg: number;
  exp_games: number;
  status: string;
  role: number;
  owner: string;
  available: boolean;
  waiver_status: "" | "free_agent" | "waivers";
};

export type DstCard = { player: string; team: string; waiver_status: string; opp: string; opp_total: number; own_total: number | null; rank: number; of: number; score: number };

export type Grades = {
  available: boolean;
  reason: string;
  as_of: string;
  decision_week: number | null;
  latest_week: number | null;
  buy_low_active: boolean;
  replacement: Record<string, number>;
  buy_low: TrackerCard[];
  next_up: TrackerCard[];
  wr_watch: { active: boolean; players: TrackerCard[] };
  dst: { mine: DstCard[]; top: DstCard[] };
};

export type Player = {
  player: string;
  pos: string;
  team: string;
  slot?: string;
  owner?: string;
  proj: Proj;
  injury?: Injury;
  roster_note?: RosterNote;
  grade?: Grade;
  stream?: Stream;
  kick?: KickStream;
  board_rank?: string | number | null;
  board_score?: string | number | null;
  depth_rank?: number;
  role_note?: string;
  status_changed?: boolean;
  lineup_slot?: string;
  prior_source?: string;
  weekly_rank?: number | null;
  weekly_value?: number | null;
  weekly_list?: string | null;
  weekly_opp?: string;
  weekly_matchup?: string;
  weekly_start_sit?: string;
  weekly_proj_fpts?: string;
  has_espn?: boolean;
  espn_pts?: string;
  espn_tip?: string;
  espn_line?: string;
  espn_gbfl?: number | null;
  espn_sim?: Record<string, number> | null;
  espn_explain?: { rows: { cat: string; input: string; pts: number | null; note?: string }[]; lines: string[]; approx_pts?: number } | null;
  vegas_total?: number | null;
  vegas_kickoff?: string;
  vegas_indoor?: boolean;
  vegas_over_under?: number | null;
  vegas_spread?: number | null;
  vegas_opp?: string;
  matchup_ratio?: number | null;
  pass_rush_skew?: number | null;
};

export type Scored = {
  player: string;
  pos: string;
  team: string;
  past: number | null;
  present: number;
  p10: number;
  future: number;
  keeper: number;
  board_rank: string | null;
  board_value: number | null;
  weekly_rank?: number | null;
  weekly_list?: string | null;
  weekly_matchup?: string;
  has_espn?: boolean;
  espn_pts?: string;
  espn_tip?: string;
  espn_line?: string;
  espn_gbfl?: number | null;
  blended: number;
  depth_rank: number;
  role_note: string;
  rankings_as_of?: string;
  grade?: Grade;
  stream?: Stream;
  kick?: KickStream;
  waiver_status?: "" | "free_agent" | "waivers";
};

export type FreshnessStatus = "fresh" | "stale" | "missing";

export type FreshnessEntry = {
  label: string;
  as_of: string;
  age_hours: number | null;
  status: FreshnessStatus;
  hint?: string;
};

export type Freshness = {
  cbs: FreshnessEntry;
  injuries: FreshnessEntry;
  espn: FreshnessEntry;
  weekly_fp: FreshnessEntry;
  vegas: FreshnessEntry;
  nflverse?: FreshnessEntry & { latest_week?: number | null };
  current_week: FreshnessEntry & { week: number | null; source: string };
};

export type CurrentWeek = { week: number | null; source: string; as_of: string };

export type Lineup = {
  starters: Player[];
  bench: Player[];
  total: number;
  objective?: string;
  objective_label?: string;
  mix?: { RB: number; WR: number; TE: number } | null;
  why: { player: string; text: string; kind?: string }[];
};

export type WeekPayload = {
  mock: boolean;
  week: number;
  team: string;
  rankings_as_of: string;
  week_fp_as_of?: string;
  week_fp_stamp?: string;
  week_fp_lists?: string[];
  espn_as_of?: string;
  espn_stamp?: string;
  espn_n?: number;
  espn_mix?: number;
  espn_mix_label?: string;
  weekly_weight?: number;
  injury_as_of: string;
  format_note: string;
  active_min?: Record<string, number>;
  active_max?: Record<string, number>;
  roster_caps?: Record<string, number>;
  data_flags?: {
    stats_3g?: boolean;
    depth?: boolean;
    injury_notes?: boolean;
    has_3g_usage?: boolean;
    espn_week_match?: boolean;
    fp_week_match?: boolean;
  };
  freshness?: Freshness;
  grades?: Grades;
  format_edges?: { player: string; pos: string; weekly_list: string; fp_rank: number; app_rank: number; gap: number; note: string }[];
  roster: Player[];
  lineups?: Record<string, Lineup>;
  lineup_mean?: Lineup;
  lineup_p50: Lineup;
  lineup_p10: Lineup;
  fa_sample?: Player[];
  waivers: {
    rankings_as_of: string;
    board_weight: number;
    weekly_weight?: number;
    caps: Record<string, number>;
    active_max?: Record<string, number>;
    recommendations: { add: Scored; drop: Scored; reason: string }[];
    roster_scored: Scored[];
    fa_top: Scored[];
    waiver_priority?: number | null;
    waiver_teams?: number | null;
    ir_candidates?: { player: string; pos: string; designation: string; note: string }[];
  };
};

export type ReportBand = "bust" | "typical" | "boom";
export type ReportDriver = "3g" | "Injury" | "Depth" | "ESPN";

export type ReportHighlight = {
  player: string;
  pos: string;
  actual: number;
  exp: number;
  why: string;
};

export type ReportGrade = {
  player: string;
  pos: string;
  slot: string;
  rec: boolean;
  actual: number;
  exp: number;
  band: ReportBand;
  delta: number;
};

export type ReportSitMiss = {
  started: string;
  sat: string;
  started_actual: number;
  sat_actual: number;
  text: string;
};

export type ReportOutlook = {
  player: string;
  pos: string;
  locked_exp: number;
  now_exp: number;
  delta: number;
  drivers: ReportDriver[];
  note: string;
};

export type ReportCard = {
  mock: boolean;
  week: number;
  team: string;
  mix_label: string;
  banner: string;
  format_note: string;
  status?: "ready" | "no_lock" | "no_actuals";
  grades_note?: string;
  outlook_note?: string;
  went_right: ReportHighlight[];
  went_wrong: ReportHighlight[];
  grades: ReportGrade[];
  sit_misses: ReportSitMiss[];
  outlook: ReportOutlook[];
  actions: { add: Scored; drop: Scored; reason: string }[];
  locked_lineup?: { player: string; pos: string; slot: string; rec: boolean; designation?: string }[];
  pending?: string[];
  tracking?: ReportTracking | null;
};

export type TrackingFlagStat = { n: number; pred?: number; actual?: number; beat?: number; hit_rate?: number };

export type ReportTracking = {
  weeks: number[];
  next_up: TrackingFlagStat;
  buy_low: TrackingFlagStat;
  flag_rows: { week: number; flag: GradeFlag; player: string; pos: string; pred: number; actual: number }[];
  par: Record<string, { n: number; mean_err: number; mae: number }>;
  dst: {
    weeks: number;
    pick_pts: number | null;
    avg_free_pts: number | null;
    rows: { week: number; pick: string; opp: string; opp_total: number; pick_pts: number; avg_free_pts: number; n_free: number }[];
  };
};
