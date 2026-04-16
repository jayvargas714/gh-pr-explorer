/**
 * TypeScript type definitions for API responses
 * This file will be populated with all types from the backend API
 */

// ============================================================================
// User & Account Types
// ============================================================================

export interface GitHubUser {
  login: string
  name: string
  avatar_url: string
}

export interface Account {
  login: string
  name: string
  avatar_url: string
  type: 'user' | 'org'
  is_personal?: boolean
}

// ============================================================================
// Repository Types
// ============================================================================

export interface Repository {
  name: string
  owner: {
    login: string
  }
  description: string | null
  isPrivate: boolean
  updatedAt: string
}

// ============================================================================
// Pull Request Types
// ============================================================================

export interface PullRequest {
  number: number
  title: string
  author: {
    login: string
    avatarUrl: string
  }
  state: 'OPEN' | 'CLOSED' | 'MERGED'
  isDraft: boolean
  createdAt: string
  updatedAt: string
  closedAt: string | null
  mergedAt: string | null
  url: string
  body: string
  headRefName: string
  baseRefName: string
  labels: Label[]
  assignees: Assignee[]
  reviewRequests: ReviewRequest[]
  reviewDecision: string | null
  reviewStatus: string
  ciStatus: string | null
  currentReviewers: Reviewer[]
  statusCheckRollup: StatusCheck[]
  mergeable: string
  additions: number
  deletions: number
  changedFiles: number
  milestone: Milestone | null
}

export interface Label {
  name: string
  color: string
}

export interface Assignee {
  login: string
  avatarUrl?: string
}

export interface Reviewer {
  login: string
  avatarUrl: string
  state: 'APPROVED' | 'CHANGES_REQUESTED' | 'COMMENTED' | 'DISMISSED' | 'PENDING'
  body?: string
}

export interface ReviewRequest {
  login: string
}

export interface StatusCheck {
  status: string
  conclusion: string | null
}

export interface Milestone {
  title: string
  number?: number
  state?: string
}

// ============================================================================
// Repository Metadata Types
// ============================================================================

export interface Team {
  slug: string
  name: string
}

// ============================================================================
// Developer Stats Types
// ============================================================================

export interface DeveloperStats {
  login: string
  avatar_url: string
  commits: number
  lines_added: number
  lines_deleted: number
  prs_authored: number
  prs_merged: number
  prs_closed: number
  prs_open: number
  reviews_given: number
  approvals: number
  changes_requested: number
  comments: number
}

// ============================================================================
// Branch Divergence Types
// ============================================================================

export interface DivergenceInfo {
  status: string
  ahead_by: number
  behind_by: number
}

export interface DivergenceMap {
  [prNumber: string]: DivergenceInfo
}

// ============================================================================
// CI/Workflow Types
// ============================================================================

export interface WorkflowRun {
  id: number
  name: string
  display_title: string
  status: string
  conclusion: string | null
  created_at: string
  updated_at: string
  event: string
  head_branch: string
  run_attempt: number
  run_number: number
  html_url: string
  actor_login: string
  duration_seconds: number
}

export interface WorkflowStats {
  total_runs: number
  all_time_total: number
  pass_rate: number
  avg_duration: number
  failure_count: number
  success_count: number
  runs_by_workflow: {
    [key: string]: {
      total: number
      failures: number
    }
  }
}

export interface Workflow {
  id: number
  name: string
  state: string
  path: string
}

// ============================================================================
// Analytics Types
// ============================================================================

export interface ContributorWeek {
  week: string
  commits: number
  additions: number
  deletions: number
}

export interface ContributorTimeSeries {
  login: string
  avatar_url: string
  total: number
  weeks: ContributorWeek[]
}

export interface CodeActivity {
  weekly_commits: WeeklyCommit[]
  code_changes: CodeChange[]
  owner_commits: number[]
  community_commits: number[]
  summary: ActivitySummary
}

export interface WeeklyCommit {
  week: string
  total: number
  days: number[]
}

export interface CodeChange {
  week: string
  additions: number
  deletions: number
}

export interface ActivitySummary {
  total_commits: number
  avg_weekly_commits: number
  total_additions: number
  total_deletions: number
  peak_week: string
  peak_commits: number
  owner_percentage: number
}

export interface LifecycleMetrics {
  median_time_to_merge: number
  avg_time_to_merge: number
  median_time_to_first_review: number
  avg_time_to_first_review: number
  stale_prs: StalePR[]
  stale_count: number
  distribution: {
    '<1h': number
    '1-4h': number
    '4-24h': number
    '1-3d': number
    '3-7d': number
    '>7d': number
  }
  pr_table: LifecyclePR[]
}

export interface StalePR {
  number: number
  title: string
  author: string
  age_days: number
}

export interface LifecyclePR {
  number: number
  title: string
  author: string
  created_at: string
  state: string
  time_to_first_review_hours: number | null
  time_to_merge_hours: number | null
  first_reviewer: string | null
}

export interface ReviewResponsiveness {
  leaderboard: ReviewerStats[]
  bottlenecks: Bottleneck[]
  avg_team_response_hours: number
  fastest_reviewer: string
  prs_awaiting_review: number
}

export interface ReviewerStats {
  reviewer: string
  avg_response_time_hours: number
  median_response_time_hours: number
  total_reviews: number
  approvals: number
  changes_requested: number
  approval_rate: number
}

export interface Bottleneck {
  number: number
  title: string
  author: string
  wait_hours: number
}

// ============================================================================
// Merge Queue Types
// ============================================================================

export interface MergeQueueItem {
  id: number
  number: number
  title: string
  url: string
  repo: string
  author: string
  additions: number
  deletions: number
  addedAt: string
  notesCount: number
  prState: string
  hasNewCommits: boolean
  lastReviewedSha: string | null
  currentSha: string | null
  hasReview: boolean
  reviewScore: number | null
  reviewId: number | null
  inlineCommentsPosted: boolean
  majorConcernsPosted: boolean
  minorIssuesPosted: boolean
  criticalPostedCount: number | null
  criticalFoundCount: number | null
  majorPostedCount: number | null
  majorFoundCount: number | null
  minorPostedCount: number | null
  minorFoundCount: number | null
  criticalIssueTitles: string[] | null
  majorIssueTitles: string[] | null
  minorIssueTitles: string[] | null
  isFollowup: boolean
  reviewDecision: string | null
  ciStatus: string | null
  isDraft: boolean
  currentReviewers: Reviewer[]
}

export interface QueueNote {
  id: number
  content: string
  createdAt: string
}

// ============================================================================
// Code Review Types
// ============================================================================

export interface Review {
  key: string
  owner: string
  repo: string
  pr_number: number
  status: 'running' | 'completed' | 'failed'
  started_at: string
  completed_at: string | null
  pr_url: string
  review_file: string
  exit_code: number | null
  error_output: string
}

export interface ReviewHistoryItem {
  id: number
  pr_number: number
  repo: string
  pr_title: string
  pr_author: string
  pr_url: string
  review_timestamp: string
  status: string
  score: number | null
  is_followup: boolean
  parent_review_id: number | null
}

// ============================================================================
// Structured Review JSON Types
// ============================================================================

export interface ReviewJSONMetadata {
  pr_number: number
  repository: string
  pr_url?: string
  pr_title?: string
  author?: string
  branch?: { head: string; base: string }
  review_date?: string
  review_type?: 'initial' | 'followup'
  files_changed?: number
  additions?: number
  deletions?: number
  description?: string
}

export interface ReviewIssueJSON {
  title: string
  location: { file: string; start_line: number | null; end_line: number | null }
  principle?: string
  problem: string
  fix?: string
  code_snippet?: string
}

export interface ReviewSectionJSON {
  type: 'critical' | 'major' | 'minor'
  display_name: string
  issues: ReviewIssueJSON[]
}

export interface ReviewRecommendation {
  priority: 'must_fix' | 'high' | 'medium' | 'low'
  text: string
}

export interface ReviewScoreJSON {
  overall: number
  breakdown?: { category: string; score: number; comment?: string }[]
  summary?: string
}

export interface ReviewFollowup {
  previous_review_id: number | null
  resolution_status: { issue: string; status: string; notes?: string }[]
}

export interface ReviewJSON {
  schema_version: string
  metadata: ReviewJSONMetadata
  summary: string
  sections: ReviewSectionJSON[]
  highlights?: string[]
  recommendations?: ReviewRecommendation[]
  score: ReviewScoreJSON
  followup?: ReviewFollowup
}

export interface ReviewDetail extends ReviewHistoryItem {
  review_file_path: string
  content: string
  content_json?: ReviewJSON | null
}

export interface ReviewStats {
  total_reviews: number
  average_score: number
  reviews_by_repo: {
    [repo: string]: number
  }
  reviews_by_month: {
    [month: string]: number
  }
  score_distribution: {
    '0-3': number
    '4-6': number
    '7-10': number
  }
  followup_count: number
}

// ============================================================================
// Repo Stats Types
// ============================================================================

export interface RepoOverview {
  name: string
  full_name: string
  description: string
  default_branch: string
  license: string | null
  created_at: string
  age_days: number
  size_kb: number
  stars: number
  forks: number
  watchers: number
  open_issues: number
}

export interface LanguageEntry {
  name: string
  bytes: number
  percentage: number
}

export interface FileExtensionEntry {
  extension: string
  count: number
  percentage: number
}

export interface RepoCodeStats {
  total_commits: number
  total_files: number
  total_contributors: number
  total_branches: number
}

export interface RepoPRStats {
  open: number
  closed: number
  merged: number
  total_all_time: number
}

export interface RepoStats {
  overview: RepoOverview
  code: RepoCodeStats
  prs: RepoPRStats
  languages: LanguageEntry[]
  files_by_extension: FileExtensionEntry[]
}

export interface RepoStatsResponse extends RepoStats, CacheMeta {}

export interface LOCEntry {
  language: string
  files: number
  blank: number
  comment: number
  code: number
}

export interface LOCTotals {
  files: number
  blank: number
  comment: number
  code: number
}

export interface LOCResult {
  loc: LOCEntry[]
  totals: LOCTotals
}

export interface LOCResponse extends LOCResult {
  last_updated: string | null
  cached: boolean
}

// ============================================================================
// Settings Types
// ============================================================================

export interface FilterSettings {
  state: string
  author: string
  assignee: string
  labels: string[]
  base: string
  head: string
  draft: string
  review: string[]
  reviewedBy: string
  reviewRequested: string
  status: string[]
  involves: string
  mentions: string
  commenter: string
  linked: string
  milestone: string
  noAssignee: boolean
  noLabel: boolean
  comments: string
  createdAfter: string
  createdBefore: string
  updatedAfter: string
  updatedBefore: string
  mergedAfter: string
  mergedBefore: string
  closedAfter: string
  closedBefore: string
  search: string
  searchIn: string[]
  reactions: string
  interactions: string
  teamReviewRequested: string
  excludeLabels: string[]
  excludeAuthor: string
  excludeMilestone: string
  sortBy: string
  sortDirection: string
  limit: number
}

export interface Settings {
  selectedAccount: string | null
  selectedRepo: string | null
  filters: FilterSettings
}

// ============================================================================
// Cache Metadata
// ============================================================================

export interface CacheMeta {
  last_updated: string | null
  cached: boolean
  stale: boolean
  refreshing: boolean
}

// ============================================================================
// API Response Types
// ============================================================================

export interface UserResponse {
  user: GitHubUser
}

export interface AccountsResponse {
  accounts: Account[]
}

export interface ReposResponse {
  repos: Repository[]
}

export interface PRsResponse {
  prs: PullRequest[]
}

export interface ContributorsResponse {
  contributors: string[]
}

export interface LabelsResponse {
  labels: string[]
}

export interface BranchesResponse {
  branches: string[]
}

export interface MilestonesResponse {
  milestones: Milestone[]
}

export interface TeamsResponse {
  teams: Team[]
}

export interface StatsResponse extends CacheMeta {
  stats: DeveloperStats[]
}

export interface DivergenceResponse {
  divergence: DivergenceMap
}

export interface WorkflowRunsResponse extends CacheMeta {
  runs: WorkflowRun[]
  stats: WorkflowStats
  workflows: Workflow[]
}

export interface ContributorTimeSeriesResponse extends CacheMeta {
  contributors: ContributorTimeSeries[]
}

export interface CodeActivityResponse extends CodeActivity, CacheMeta {}

export interface LifecycleMetricsResponse extends LifecycleMetrics, CacheMeta {}

export interface ReviewResponsivenessResponse extends ReviewResponsiveness, CacheMeta {}

export interface MergeQueueResponse {
  queue: MergeQueueItem[]
}

export interface QueueNotesResponse {
  notes: QueueNote[]
}

export interface ReviewsResponse {
  reviews: Review[]
}

export interface ReviewHistoryResponse {
  reviews: ReviewHistoryItem[]
  total: number
}

export interface ReviewStatsResponse extends ReviewStats {}

export interface MessageResponse {
  message: string
}

export interface SectionIssuePreview {
  index: number
  title: string
  path: string
  start_line: number | null
  end_line: number | null
  body: string
}

export interface SectionIssuesResponse {
  issues: SectionIssuePreview[]
  section: string
  section_heading: string
}

// ============================================================================
// Verdict Types
// ============================================================================

export type VerdictEvent = 'APPROVE' | 'REQUEST_CHANGES' | 'COMMENT'

export interface VerdictInlineComment {
  path: string
  body: string
  start_line: number | null
  end_line: number | null
  title?: string
  section?: string
}

export interface VerdictRequest {
  event: VerdictEvent
  body: string
  inline_comments?: VerdictInlineComment[]
  review_id?: number
}

export interface VerdictResponse {
  message: string
  event: string
  pr_number: number
  inline_posted: number
  inline_errors: string[] | null
  fallback_used: boolean
  section_details?: {
    critical?: { posted: number; found: number; failed_titles: string[] }
    major?: { posted: number; found: number; failed_titles: string[] }
    minor?: { posted: number; found: number; failed_titles: string[] }
  }
}
