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

export type Breakout = { flag: string; why: string } | null;

export type Player = {
  player: string;
  pos: string;
  team: string;
  slot?: string;
  owner?: string;
  proj: Proj;
  injury?: Injury;
  roster_note?: RosterNote;
  breakout?: Breakout;
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
  blended: number;
  depth_rank: number;
  role_note: string;
  rankings_as_of?: string;
  breakout?: Breakout;
};

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
  weekly_weight?: number;
  injury_as_of: string;
  format_note: string;
  active_min?: Record<string, number>;
  active_max?: Record<string, number>;
  roster_caps?: Record<string, number>;
  data_flags?: { stats_3g?: boolean; depth?: boolean; injury_notes?: boolean; has_3g_usage?: boolean };
  roster: Player[];
  lineups?: Record<string, Lineup>;
  lineup_p50: Lineup;
  lineup_p10: Lineup;
  waivers: {
    rankings_as_of: string;
    board_weight: number;
    weekly_weight?: number;
    caps: Record<string, number>;
    active_max?: Record<string, number>;
    recommendations: { add: Scored; drop: Scored; reason: string }[];
    roster_scored: Scored[];
    fa_top: Scored[];
  };
};
