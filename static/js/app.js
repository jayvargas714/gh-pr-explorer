/**
 * GitHub PR Explorer - Vue.js Application
 * A lightweight web application to browse, filter, and explore GitHub Pull Requests
 */

const { createApp, ref, reactive, computed, watch, onMounted, nextTick } = Vue;

createApp({
    setup() {
        // Theme
        const darkMode = ref(true);

        // Accounts (orgs + personal)
        const accounts = ref([]);
        const accountsLoading = ref(false);
        const selectedAccount = ref(null);

        // Repositories
        const repos = ref([]);
        const reposLoading = ref(false);
        const repoSearch = ref('');
        const showRepoDropdown = ref(false);
        const selectedRepo = ref(null);

        // Filter panel state
        const filtersExpanded = ref(true);
        const activeFilterTab = ref('basic');

        // Filters - organized by category
        const filters = reactive({
            // Basic filters
            state: 'open',
            author: '',
            assignee: '',

            // Labels (multiple)
            labels: [],
            noLabel: false,

            // Branches
            base: '',
            head: '',

            // Draft status
            draft: '',  // '', 'true', 'false'

            // Review filters (multi-select with OR logic)
            review: [],  // ['none', 'required', 'approved', 'changes_requested']
            reviewedBy: '',
            reviewRequested: '',

            // CI/Status (multi-select with OR logic)
            status: [],  // ['pending', 'success', 'failure']

            // Advanced options (disabled by default)
            advancedEnabled: {
                reactions: false,
                interactions: false,
                teamReview: false,
                excludeLabels: false,
                excludeAuthors: false,
                excludeMilestone: false,
                sortBy: false
            },

            // Advanced filter values
            reactionsOp: '>=',
            reactionsCount: '',
            interactionsOp: '>=',
            interactionsCount: '',
            teamReviewRequested: '',
            excludeLabels: [],
            excludeAuthor: '',
            excludeMilestone: '',
            sortBy: '',  // 'reactions', 'interactions', 'created', 'updated', 'comments'
            sortDirection: 'desc',

            // People filters
            involves: '',
            mentions: '',
            commenter: '',
            noAssignee: false,

            // Linked issues
            linked: '',  // '', 'true', 'false'

            // Milestone
            milestone: '',

            // Comments
            comments: '',  // e.g., '>5', '>=10', '0'

            // Date filters
            createdAfter: '',
            createdBefore: '',
            updatedAfter: '',
            updatedBefore: '',
            mergedAfter: '',
            mergedBefore: '',
            closedAfter: '',
            closedBefore: '',

            // Text search
            search: '',
            searchIn: [],  // ['title', 'body', 'comments']

            // Limit
            limit: 30
        });

        // Filter options (populated from API)
        const contributors = ref([]);
        const labels = ref([]);
        const branches = ref([]);
        const milestones = ref([]);
        const teams = ref([]);

        // Pull Requests
        const prs = ref([]);
        const loading = ref(false);
        const error = ref(null);

        // View Toggle (PRs vs Stats)
        const activeView = ref('prs');

        // Developer Stats
        const statsLoading = ref(false);
        const developerStats = ref([]);
        const statsError = ref(null);
        const statsSortBy = ref('commits');
        const statsSortDirection = ref('desc');
        const statsLastUpdated = ref(null);
        const statsFromCache = ref(false);
        const statsRefreshing = ref(false);  // Background refresh in progress
        const statsStale = ref(false);

        // Description Modal
        const descriptionModal = reactive({
            show: false,
            pr: null
        });

        // Merge Queue
        const mergeQueue = ref([]);
        const showQueuePanel = ref(false);
        const queueRefreshing = ref(false);

        // Queue Notes
        const queueNotes = ref({});  // { "pr_number:repo": [notes] }
        const notesLoading = ref({});  // { "pr_number:repo": boolean }
        const openNotesDropdowns = ref({});  // { "pr_number:repo": boolean }
        const selectedNoteIndex = ref({});  // { "pr_number:repo": number }
        const notesModal = reactive({
            show: false,
            queueItem: null,
            mode: 'add',  // 'add' | 'view'
            newNoteContent: ''
        });

        // Code Reviews
        const activeReviews = ref({});  // key: "owner/repo/pr_number", value: {status, startedAt, reviewFile}
        const reviewPollingInterval = ref(null);

        // Review History
        const reviewHistory = ref([]);
        const historyLoading = ref(false);
        const historyFilters = reactive({
            repo: '',
            author: '',
            search: ''
        });
        const selectedHistoryReview = ref(null);
        const showHistoryPanel = ref(false);
        const showReviewViewer = ref(false);
        const reviewViewerContent = ref(null);
        const copySuccess = ref(false);  // For copy button feedback
        const prReviewCache = ref({});  // Cache: "owner/repo/pr_number" -> latest review info

        // New Commits Detection
        const newCommitsInfo = ref({});  // Cache: "owner/repo/pr_number" -> { has_new_commits, last_reviewed_sha, current_sha }

        // Inline Comments Posting
        const postingInlineComments = ref({});  // key: review_id, value: boolean (loading state)

        // Active filters count
        const activeFiltersCount = computed(() => {
            let count = 0;
            if (filters.state !== 'open') count++;
            if (filters.author) count++;
            if (filters.assignee) count++;
            if (filters.labels.length > 0) count++;
            if (filters.noLabel) count++;
            if (filters.base) count++;
            if (filters.head) count++;
            if (filters.draft) count++;
            if (filters.review.length > 0) count++;
            if (filters.reviewedBy) count++;
            if (filters.reviewRequested) count++;
            if (filters.status.length > 0) count++;
            if (filters.involves) count++;
            if (filters.mentions) count++;
            if (filters.commenter) count++;
            if (filters.noAssignee) count++;
            if (filters.linked) count++;
            if (filters.milestone) count++;
            if (filters.comments) count++;
            if (filters.createdAfter) count++;
            if (filters.createdBefore) count++;
            if (filters.updatedAfter) count++;
            if (filters.updatedBefore) count++;
            if (filters.mergedAfter) count++;
            if (filters.mergedBefore) count++;
            if (filters.closedAfter) count++;
            if (filters.closedBefore) count++;
            if (filters.search) count++;
            // Advanced filters
            if (filters.advancedEnabled.reactions && filters.reactionsCount) count++;
            if (filters.advancedEnabled.interactions && filters.interactionsCount) count++;
            if (filters.advancedEnabled.teamReview && filters.teamReviewRequested) count++;
            if (filters.advancedEnabled.excludeLabels && filters.excludeLabels.length > 0) count++;
            if (filters.advancedEnabled.excludeAuthors && filters.excludeAuthor) count++;
            if (filters.advancedEnabled.excludeMilestone && filters.excludeMilestone) count++;
            if (filters.advancedEnabled.sortBy && filters.sortBy) count++;
            return count;
        });

        // Computed: sorted developer stats
        const sortedDeveloperStats = computed(() => {
            if (!developerStats.value.length) return [];

            return [...developerStats.value].sort((a, b) => {
                const aVal = a[statsSortBy.value] || 0;
                const bVal = b[statsSortBy.value] || 0;

                if (statsSortDirection.value === 'asc') {
                    return aVal - bVal;
                }
                return bVal - aVal;
            });
        });

        // Computed: filtered repos based on search
        const filteredRepos = computed(() => {
            if (!repoSearch.value) {
                return repos.value.slice(0, 30);
            }
            const search = repoSearch.value.toLowerCase();
            return repos.value
                .filter(repo => {
                    const fullName = `${repo.owner.login}/${repo.name}`.toLowerCase();
                    return fullName.includes(search);
                })
                .slice(0, 30);
        });

        // Methods
        const toggleTheme = () => {
            darkMode.value = !darkMode.value;
            document.body.classList.toggle('dark-mode', darkMode.value);
            localStorage.setItem('darkMode', darkMode.value);
        };

        const fetchAccounts = async () => {
            accountsLoading.value = true;
            try {
                const response = await fetch('/api/orgs');
                const data = await response.json();
                if (data.error) {
                    throw new Error(data.error);
                }
                accounts.value = data.accounts || [];
            } catch (err) {
                console.error('Failed to fetch accounts:', err);
            } finally {
                accountsLoading.value = false;
            }
        };

        const selectAccount = async (account) => {
            selectedAccount.value = account;
            selectedRepo.value = null;
            prs.value = [];
            resetFilterOptions();
            resetFilters();
            await fetchRepos();
        };

        const clearAccount = () => {
            selectedAccount.value = null;
            selectedRepo.value = null;
            repos.value = [];
            prs.value = [];
            resetFilterOptions();
            resetFilters();
        };

        const resetFilterOptions = () => {
            contributors.value = [];
            labels.value = [];
            branches.value = [];
            milestones.value = [];
            teams.value = [];
        };

        const fetchRepos = async () => {
            if (!selectedAccount.value) return;

            reposLoading.value = true;
            try {
                const owner = selectedAccount.value.login;
                const response = await fetch(`/api/repos?owner=${encodeURIComponent(owner)}&limit=200`);
                const data = await response.json();
                if (data.error) {
                    throw new Error(data.error);
                }
                repos.value = data.repos || [];
            } catch (err) {
                console.error('Failed to fetch repos:', err);
            } finally {
                reposLoading.value = false;
            }
        };

        const filterRepos = () => {
            showRepoDropdown.value = true;
        };

        const selectRepo = (repo) => {
            selectedRepo.value = repo;
            repoSearch.value = '';
            showRepoDropdown.value = false;
            fetchRepoMetadata();
            fetchPRs();
        };

        const clearRepo = () => {
            selectedRepo.value = null;
            prs.value = [];
            developerStats.value = [];
            activeView.value = 'prs';
            resetFilterOptions();
            resetFilters();
        };

        const fetchRepoMetadata = async () => {
            if (!selectedRepo.value) return;

            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;

            // Fetch all metadata in parallel
            try {
                const [contribRes, labelsRes, branchesRes, milestonesRes, teamsRes] = await Promise.all([
                    fetch(`/api/repos/${owner}/${repo}/contributors`),
                    fetch(`/api/repos/${owner}/${repo}/labels`),
                    fetch(`/api/repos/${owner}/${repo}/branches`),
                    fetch(`/api/repos/${owner}/${repo}/milestones`),
                    fetch(`/api/repos/${owner}/${repo}/teams`)
                ]);

                const contribData = await contribRes.json();
                const labelsData = await labelsRes.json();
                const branchesData = await branchesRes.json();
                const milestonesData = await milestonesRes.json();
                const teamsData = await teamsRes.json();

                contributors.value = contribData.contributors || [];
                labels.value = labelsData.labels || [];
                branches.value = branchesData.branches || [];
                milestones.value = milestonesData.milestones || [];
                teams.value = teamsData.teams || [];
            } catch (err) {
                console.error('Failed to fetch repo metadata:', err);
            }
        };

        const fetchPRs = async () => {
            if (!selectedRepo.value) return;

            loading.value = true;
            error.value = null;

            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;

            // Build query params
            const params = new URLSearchParams();

            // Basic filters
            params.append('state', filters.state);
            params.append('limit', filters.limit);

            if (filters.author) params.append('author', filters.author);
            if (filters.assignee) params.append('assignee', filters.assignee);
            if (filters.labels.length > 0) params.append('labels', filters.labels.join(','));
            if (filters.noLabel) params.append('noLabel', 'true');
            if (filters.base) params.append('base', filters.base);
            if (filters.head) params.append('head', filters.head);
            if (filters.draft) params.append('draft', filters.draft);

            // Review filters (multi-select with OR logic)
            if (filters.review.length > 0) params.append('review', filters.review.join(','));
            if (filters.reviewedBy) params.append('reviewedBy', filters.reviewedBy);
            if (filters.reviewRequested) params.append('reviewRequested', filters.reviewRequested);

            // CI/Status (multi-select with OR logic)
            if (filters.status.length > 0) params.append('status', filters.status.join(','));

            // People filters
            if (filters.involves) params.append('involves', filters.involves);
            if (filters.mentions) params.append('mentions', filters.mentions);
            if (filters.commenter) params.append('commenter', filters.commenter);
            if (filters.noAssignee) params.append('noAssignee', 'true');

            // Linked issues
            if (filters.linked) params.append('linked', filters.linked);

            // Milestone
            if (filters.milestone) params.append('milestone', filters.milestone);

            // Comments
            if (filters.comments) params.append('comments', filters.comments);

            // Date filters
            if (filters.createdAfter) params.append('createdAfter', filters.createdAfter);
            if (filters.createdBefore) params.append('createdBefore', filters.createdBefore);
            if (filters.updatedAfter) params.append('updatedAfter', filters.updatedAfter);
            if (filters.updatedBefore) params.append('updatedBefore', filters.updatedBefore);
            if (filters.mergedAfter) params.append('mergedAfter', filters.mergedAfter);
            if (filters.mergedBefore) params.append('mergedBefore', filters.mergedBefore);
            if (filters.closedAfter) params.append('closedAfter', filters.closedAfter);
            if (filters.closedBefore) params.append('closedBefore', filters.closedBefore);

            // Text search
            if (filters.search) params.append('search', filters.search);
            if (filters.searchIn.length > 0) params.append('searchIn', filters.searchIn.join(','));

            // Advanced filters (only if enabled)
            if (filters.advancedEnabled.reactions && filters.reactionsCount) {
                params.append('reactions', filters.reactionsOp + filters.reactionsCount);
            }
            if (filters.advancedEnabled.interactions && filters.interactionsCount) {
                params.append('interactions', filters.interactionsOp + filters.interactionsCount);
            }
            if (filters.advancedEnabled.teamReview && filters.teamReviewRequested) {
                params.append('teamReviewRequested', filters.teamReviewRequested);
            }
            if (filters.advancedEnabled.excludeLabels && filters.excludeLabels.length > 0) {
                params.append('excludeLabels', filters.excludeLabels.join(','));
            }
            if (filters.advancedEnabled.excludeAuthors && filters.excludeAuthor) {
                params.append('excludeAuthor', filters.excludeAuthor);
            }
            if (filters.advancedEnabled.excludeMilestone && filters.excludeMilestone) {
                params.append('excludeMilestone', filters.excludeMilestone);
            }
            if (filters.advancedEnabled.sortBy && filters.sortBy) {
                params.append('sortBy', filters.sortBy);
                params.append('sortDirection', filters.sortDirection);
            }

            try {
                const response = await fetch(`/api/repos/${owner}/${repo}/prs?${params}`);
                const data = await response.json();

                if (data.error) {
                    throw new Error(data.error);
                }

                prs.value = data.prs || [];

                // Fetch review info for all PRs and refresh merge queue in background
                nextTick(() => {
                    fetchReviewInfoForPRs();
                    fetchMergeQueue();  // Sync merge queue with latest PR states
                });
            } catch (err) {
                error.value = err.message || 'Failed to fetch pull requests';
                console.error('Failed to fetch PRs:', err);
            } finally {
                loading.value = false;
            }
        };

        const fetchDeveloperStats = async (forceRefresh = false) => {
            if (!selectedRepo.value) return;

            // Only show loading spinner on initial load or force refresh
            if (!developerStats.value.length || forceRefresh) {
                statsLoading.value = true;
            }
            statsError.value = null;

            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;

            try {
                const url = forceRefresh
                    ? `/api/repos/${owner}/${repo}/stats?refresh=true`
                    : `/api/repos/${owner}/${repo}/stats`;
                const response = await fetch(url);
                const data = await response.json();

                if (data.error) {
                    throw new Error(data.error);
                }

                developerStats.value = data.stats || [];
                statsLastUpdated.value = data.last_updated ? new Date(data.last_updated) : null;
                statsFromCache.value = data.cached || false;
                statsRefreshing.value = data.refreshing || false;
                statsStale.value = data.stale || false;

                // If refreshing in background, poll for completion
                if (data.refreshing && !forceRefresh) {
                    setTimeout(() => {
                        // Check again in 5 seconds to see if refresh completed
                        fetchDeveloperStats(false);
                    }, 5000);
                }
            } catch (err) {
                statsError.value = err.message || 'Failed to fetch developer stats';
                console.error('Failed to fetch stats:', err);
            } finally {
                statsLoading.value = false;
            }
        };

        const refreshDeveloperStats = () => {
            fetchDeveloperStats(true);
        };

        const formatStatsLastUpdated = () => {
            if (!statsLastUpdated.value) return 'Never';
            const now = new Date();
            const diff = now - statsLastUpdated.value;
            const minutes = Math.floor(diff / 60000);
            const hours = Math.floor(minutes / 60);

            if (minutes < 1) return 'Just now';
            if (minutes < 60) return `${minutes} minute${minutes !== 1 ? 's' : ''} ago`;
            if (hours < 24) return `${hours} hour${hours !== 1 ? 's' : ''} ago`;
            return statsLastUpdated.value.toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit'
            });
        };

        const setActiveView = (view) => {
            activeView.value = view;
            if (view === 'stats' && developerStats.value.length === 0) {
                fetchDeveloperStats();
            }
        };

        const sortStats = (column) => {
            if (statsSortBy.value === column) {
                // Toggle direction if same column
                statsSortDirection.value = statsSortDirection.value === 'desc' ? 'asc' : 'desc';
            } else {
                statsSortBy.value = column;
                statsSortDirection.value = 'desc';
            }
        };

        const getMergeRate = (dev) => {
            if (!dev.prs_authored || dev.prs_authored === 0) return 0;
            return Math.round((dev.prs_merged / dev.prs_authored) * 100);
        };

        const formatNumber = (num) => {
            if (num >= 1000000) {
                return (num / 1000000).toFixed(1) + 'M';
            }
            if (num >= 1000) {
                return (num / 1000).toFixed(1) + 'K';
            }
            return num.toString();
        };

        const resetFilters = () => {
            filters.state = 'open';
            filters.author = '';
            filters.assignee = '';
            filters.labels = [];
            filters.noLabel = false;
            filters.base = '';
            filters.head = '';
            filters.draft = '';
            filters.review = [];
            filters.reviewedBy = '';
            filters.reviewRequested = '';
            filters.status = [];
            filters.involves = '';
            filters.mentions = '';
            filters.commenter = '';
            filters.noAssignee = false;
            filters.linked = '';
            filters.milestone = '';
            filters.comments = '';
            filters.createdAfter = '';
            filters.createdBefore = '';
            filters.updatedAfter = '';
            filters.updatedBefore = '';
            filters.mergedAfter = '';
            filters.mergedBefore = '';
            filters.closedAfter = '';
            filters.closedBefore = '';
            filters.search = '';
            filters.searchIn = [];
            filters.limit = 30;
            // Reset advanced filters
            filters.advancedEnabled.reactions = false;
            filters.advancedEnabled.interactions = false;
            filters.advancedEnabled.teamReview = false;
            filters.advancedEnabled.excludeLabels = false;
            filters.advancedEnabled.excludeAuthors = false;
            filters.advancedEnabled.excludeMilestone = false;
            filters.advancedEnabled.sortBy = false;
            filters.reactionsOp = '>=';
            filters.reactionsCount = '';
            filters.interactionsOp = '>=';
            filters.interactionsCount = '';
            filters.teamReviewRequested = '';
            filters.excludeLabels = [];
            filters.excludeAuthor = '';
            filters.excludeMilestone = '';
            filters.sortBy = '';
            filters.sortDirection = 'desc';
        };

        const toggleLabel = (label) => {
            const idx = filters.labels.indexOf(label);
            if (idx === -1) {
                filters.labels.push(label);
            } else {
                filters.labels.splice(idx, 1);
            }
        };

        const toggleSearchIn = (field) => {
            const idx = filters.searchIn.indexOf(field);
            if (idx === -1) {
                filters.searchIn.push(field);
            } else {
                filters.searchIn.splice(idx, 1);
            }
        };

        const toggleReview = (value) => {
            const idx = filters.review.indexOf(value);
            if (idx === -1) {
                filters.review.push(value);
            } else {
                filters.review.splice(idx, 1);
            }
        };

        const toggleStatus = (value) => {
            const idx = filters.status.indexOf(value);
            if (idx === -1) {
                filters.status.push(value);
            } else {
                filters.status.splice(idx, 1);
            }
        };

        const toggleExcludeLabel = (label) => {
            const idx = filters.excludeLabels.indexOf(label);
            if (idx === -1) {
                filters.excludeLabels.push(label);
            } else {
                filters.excludeLabels.splice(idx, 1);
            }
        };

        const getStateClass = (pr) => {
            if (pr.state === 'MERGED') return 'state-merged';
            if (pr.state === 'CLOSED') return 'state-closed';
            return 'state-open';
        };

        const getStateIcon = (pr) => {
            if (pr.state === 'MERGED') return '\u2295';
            if (pr.state === 'CLOSED') return '\u2715';
            return '\u25CB';
        };

        const getStateLabel = (pr) => {
            if (pr.state === 'MERGED') return 'Merged';
            if (pr.state === 'CLOSED') return 'Closed';
            return 'Open';
        };

        const getReviewClass = (pr) => {
            const status = pr.reviewStatus;
            if (status === 'approved') return 'review-approved';
            if (status === 'changes_requested') return 'review-changes';
            return 'review-pending';
        };

        // GitHub review status helpers
        const getGhReviewLabel = (status) => {
            const labels = {
                'approved': 'Approved',
                'changes_requested': 'Changes',
                'review_required': 'Review needed'
            };
            return labels[status] || status;
        };

        const getGhReviewTitle = (status) => {
            const titles = {
                'approved': 'Changes approved',
                'changes_requested': 'Changes requested',
                'review_required': 'Review required'
            };
            return titles[status] || status;
        };

        // CI status helpers
        const getCiStatusLabel = (status) => {
            const labels = {
                'success': 'CI passed',
                'failure': 'CI failed',
                'pending': 'CI running',
                'neutral': 'CI skipped'
            };
            return labels[status] || status;
        };

        const getCiStatusTitle = (status) => {
            const titles = {
                'success': 'All checks passed',
                'failure': 'Some checks failed',
                'pending': 'Checks in progress',
                'neutral': 'Checks skipped or neutral'
            };
            return titles[status] || status;
        };

        const formatDate = (dateString) => {
            if (!dateString) return '';
            const date = new Date(dateString);
            const now = new Date();
            const diffMs = now - date;
            const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

            // Format local time as HH:MM
            const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            // For today, show relative time + actual time
            if (diffDays === 0) {
                const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
                if (diffHours === 0) {
                    const diffMins = Math.floor(diffMs / (1000 * 60));
                    return `${diffMins}m ago (${timeStr})`;
                }
                return `${diffHours}h ago (${timeStr})`;
            }

            // For yesterday, show "yesterday" + time
            if (diffDays === 1) return `yesterday ${timeStr}`;

            // For this week, show day + time
            if (diffDays < 7) return `${diffDays}d ago ${timeStr}`;

            // For older dates, show date + time
            const dateStr = date.toLocaleDateString([], { month: 'short', day: 'numeric' });
            if (diffDays < 365) return `${dateStr} ${timeStr}`;

            // For dates over a year, include the year
            const fullDateStr = date.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
            return `${fullDateStr} ${timeStr}`;
        };

        const truncateBody = (body) => {
            if (!body) return '';
            const maxLength = 500;
            if (body.length <= maxLength) return body;
            return body.substring(0, maxLength) + '...';
        };

        const renderMarkdown = (text) => {
            if (!text) return '<p class="no-description">No description provided.</p>';
            try {
                // Configure marked for GitHub-flavored markdown
                marked.setOptions({
                    breaks: true,
                    gfm: true
                });
                return marked.parse(text);
            } catch (e) {
                console.error('Markdown parsing error:', e);
                return `<pre>${text}</pre>`;
            }
        };

        const openDescriptionModal = (pr) => {
            descriptionModal.pr = pr;
            descriptionModal.show = true;
            // Prevent body scroll when modal is open
            document.body.style.overflow = 'hidden';
        };

        const closeDescriptionModal = () => {
            descriptionModal.show = false;
            descriptionModal.pr = null;
            document.body.style.overflow = '';
        };

        // Close modal on Escape key
        const handleKeydown = (event) => {
            if (event.key === 'Escape' && descriptionModal.show) {
                closeDescriptionModal();
            }
        };

        // Click outside to close dropdown
        const handleClickOutside = (event) => {
            const searchWrapper = document.querySelector('.search-input-wrapper');
            if (searchWrapper && !searchWrapper.contains(event.target)) {
                showRepoDropdown.value = false;
            }
        };

        // Merge Queue Methods
        const fetchMergeQueue = async () => {
            try {
                const response = await fetch('/api/merge-queue');
                const data = await response.json();
                mergeQueue.value = data.queue || [];
            } catch (err) {
                console.error('Failed to fetch merge queue:', err);
            }
        };

        const refreshMergeQueue = async () => {
            queueRefreshing.value = true;
            try {
                await fetchMergeQueue();
            } finally {
                queueRefreshing.value = false;
            }
        };

        const addToQueue = async (pr) => {
            if (!selectedRepo.value) return;

            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;

            const queueItem = {
                number: pr.number,
                title: pr.title,
                url: pr.url,
                author: pr.author?.login || 'unknown',
                additions: pr.additions || 0,
                deletions: pr.deletions || 0,
                repo: `${owner}/${repo}`
            };

            try {
                const response = await fetch('/api/merge-queue', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(queueItem)
                });

                if (response.ok) {
                    const data = await response.json();
                    mergeQueue.value.push(data.item);
                } else {
                    const error = await response.json();
                    console.error('Failed to add to queue:', error.error);
                }
            } catch (err) {
                console.error('Failed to add to queue:', err);
            }
        };

        const removeFromQueue = async (prNumber, repo) => {
            try {
                const response = await fetch(`/api/merge-queue/${prNumber}?repo=${encodeURIComponent(repo)}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    mergeQueue.value = mergeQueue.value.filter(
                        item => !(item.number === prNumber && item.repo === repo)
                    );
                } else {
                    const error = await response.json();
                    console.error('Failed to remove from queue:', error.error);
                }
            } catch (err) {
                console.error('Failed to remove from queue:', err);
            }
        };

        const isInQueue = (prNumber) => {
            if (!selectedRepo.value) return false;
            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;
            const fullRepo = `${owner}/${repo}`;
            return mergeQueue.value.some(item => item.number === prNumber && item.repo === fullRepo);
        };

        const toggleQueuePanel = () => {
            showQueuePanel.value = !showQueuePanel.value;
            if (showQueuePanel.value) {
                document.body.style.overflow = 'hidden';
            } else {
                document.body.style.overflow = '';
            }
        };

        const closeQueuePanel = () => {
            showQueuePanel.value = false;
            document.body.style.overflow = '';
        };

        const moveQueueItem = async (index, direction) => {
            const newIndex = index + direction;
            if (newIndex < 0 || newIndex >= mergeQueue.value.length) return;

            // Swap items locally first
            const items = [...mergeQueue.value];
            [items[index], items[newIndex]] = [items[newIndex], items[index]];
            mergeQueue.value = items;

            // Send reorder to backend
            try {
                const order = items.map(item => ({ number: item.number, repo: item.repo }));
                await fetch('/api/merge-queue/reorder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ order })
                });
            } catch (err) {
                console.error('Failed to reorder queue:', err);
                // Reload queue to sync with backend
                fetchMergeQueue();
            }
        };

        const clearQueue = async () => {
            // Remove all items one by one
            const items = [...mergeQueue.value];
            for (const item of items) {
                await removeFromQueue(item.number, item.repo);
            }
        };

        // Queue Notes Methods
        const getQueueKey = (item) => {
            return `${item.number}:${item.repo}`;
        };

        const getNotesCount = (item) => {
            return item.notesCount || 0;
        };

        const getItemNotes = (item) => {
            const key = getQueueKey(item);
            return queueNotes.value[key] || [];
        };

        const fetchNotesForQueueItem = async (item) => {
            const key = getQueueKey(item);
            notesLoading.value[key] = true;

            try {
                const response = await fetch(
                    `/api/merge-queue/${item.number}/notes?repo=${encodeURIComponent(item.repo)}`
                );
                const data = await response.json();

                if (response.ok) {
                    queueNotes.value[key] = data.notes || [];
                    // Select first note by default
                    if (data.notes && data.notes.length > 0) {
                        selectedNoteIndex.value[key] = 0;
                    }
                } else {
                    console.error('Failed to fetch notes:', data.error);
                }
            } catch (err) {
                console.error('Failed to fetch notes:', err);
            } finally {
                notesLoading.value[key] = false;
            }
        };

        const toggleNotesDropdown = async (item) => {
            const key = getQueueKey(item);

            if (openNotesDropdowns.value[key]) {
                // Close dropdown
                openNotesDropdowns.value[key] = false;
            } else {
                // Close all other dropdowns
                Object.keys(openNotesDropdowns.value).forEach(k => {
                    openNotesDropdowns.value[k] = false;
                });

                // Open this dropdown
                openNotesDropdowns.value[key] = true;

                // Fetch notes if not already loaded
                if (!queueNotes.value[key]) {
                    await fetchNotesForQueueItem(item);
                }
            }
        };

        const isNotesDropdownOpen = (item) => {
            const key = getQueueKey(item);
            return openNotesDropdowns.value[key] || false;
        };

        const selectNote = (item, index) => {
            const key = getQueueKey(item);
            selectedNoteIndex.value[key] = index;
        };

        const getSelectedNote = (item) => {
            const key = getQueueKey(item);
            const notes = queueNotes.value[key] || [];
            const index = selectedNoteIndex.value[key] || 0;
            return notes[index] || null;
        };

        const openNotesModal = (item, mode = 'add') => {
            notesModal.queueItem = item;
            notesModal.mode = mode;
            notesModal.newNoteContent = '';
            notesModal.show = true;
            document.body.style.overflow = 'hidden';
        };

        const closeNotesModal = () => {
            notesModal.show = false;
            notesModal.queueItem = null;
            notesModal.newNoteContent = '';
            document.body.style.overflow = '';
        };

        const saveNote = async () => {
            if (!notesModal.queueItem || !notesModal.newNoteContent.trim()) return;

            const item = notesModal.queueItem;
            const content = notesModal.newNoteContent.trim();

            try {
                const response = await fetch(
                    `/api/merge-queue/${item.number}/notes?repo=${encodeURIComponent(item.repo)}`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ content })
                    }
                );

                const data = await response.json();

                if (response.ok) {
                    // Add note to local state
                    const key = getQueueKey(item);
                    if (!queueNotes.value[key]) {
                        queueNotes.value[key] = [];
                    }
                    // Add to beginning since newest first
                    queueNotes.value[key].unshift(data.note);

                    // Update notes count in queue item
                    const queueItem = mergeQueue.value.find(
                        q => q.number === item.number && q.repo === item.repo
                    );
                    if (queueItem) {
                        queueItem.notesCount = (queueItem.notesCount || 0) + 1;
                    }

                    // Select the new note
                    selectedNoteIndex.value[key] = 0;

                    // Close modal
                    closeNotesModal();
                } else {
                    console.error('Failed to save note:', data.error);
                    alert('Failed to save note: ' + data.error);
                }
            } catch (err) {
                console.error('Failed to save note:', err);
                alert('Failed to save note. Check console for details.');
            }
        };

        const deleteNote = async (noteId, item) => {
            if (!confirm('Delete this note?')) return;

            try {
                const response = await fetch(`/api/merge-queue/notes/${noteId}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    // Remove note from local state
                    const key = getQueueKey(item);
                    if (queueNotes.value[key]) {
                        queueNotes.value[key] = queueNotes.value[key].filter(n => n.id !== noteId);

                        // Update selected index if needed
                        const notes = queueNotes.value[key];
                        if (notes.length === 0) {
                            delete selectedNoteIndex.value[key];
                        } else if (selectedNoteIndex.value[key] >= notes.length) {
                            selectedNoteIndex.value[key] = notes.length - 1;
                        }
                    }

                    // Update notes count in queue item
                    const queueItem = mergeQueue.value.find(
                        q => q.number === item.number && q.repo === item.repo
                    );
                    if (queueItem && queueItem.notesCount > 0) {
                        queueItem.notesCount -= 1;
                    }
                } else {
                    const error = await response.json();
                    console.error('Failed to delete note:', error.error);
                }
            } catch (err) {
                console.error('Failed to delete note:', err);
            }
        };

        const truncateNote = (content) => {
            if (!content) return '';
            const firstLine = content.split('\n')[0];
            if (firstLine.length > 40) {
                return firstLine.substring(0, 40) + '...';
            }
            return firstLine;
        };

        const formatNoteDate = (dateStr) => {
            if (!dateStr) return '';
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit'
            });
        };

        // Code Review Methods
        // Review Error Modal
        const reviewErrorModal = reactive({
            show: false,
            prNumber: null,
            prTitle: '',
            errorOutput: '',
            exitCode: null
        });

        const openReviewErrorModal = (prNumber, prTitle, errorOutput, exitCode) => {
            reviewErrorModal.prNumber = prNumber;
            reviewErrorModal.prTitle = prTitle || `PR #${prNumber}`;
            reviewErrorModal.errorOutput = errorOutput || 'No error details available.';
            reviewErrorModal.exitCode = exitCode;
            reviewErrorModal.show = true;
            document.body.style.overflow = 'hidden';
        };

        const closeReviewErrorModal = () => {
            reviewErrorModal.show = false;
            reviewErrorModal.prNumber = null;
            reviewErrorModal.prTitle = '';
            reviewErrorModal.errorOutput = '';
            reviewErrorModal.exitCode = null;
            document.body.style.overflow = '';
        };

        const fetchReviews = async () => {
            try {
                const response = await fetch('/api/reviews');
                const data = await response.json();
                if (data.reviews) {
                    // Track reviews that just completed to refresh their cache
                    const completedReviews = [];

                    // Update activeReviews from server state
                    const newReviews = {};
                    for (const review of data.reviews) {
                        const oldStatus = activeReviews.value[review.key]?.status;
                        const newStatus = review.status;

                        // Track if this review just completed
                        if (oldStatus === 'running' && newStatus === 'completed') {
                            completedReviews.push(review);
                        }

                        newReviews[review.key] = {
                            status: review.status,
                            startedAt: review.started_at,
                            completedAt: review.completed_at,
                            reviewFile: review.review_file,
                            exitCode: review.exit_code,
                            errorOutput: review.error_output
                        };
                    }
                    activeReviews.value = newReviews;

                    // Refresh PR review cache for completed reviews
                    for (const review of completedReviews) {
                        // Invalidate cache entry so it gets re-fetched
                        delete prReviewCache.value[review.key];
                        // Re-fetch the review info
                        const parts = review.key.split('/');
                        if (parts.length === 3) {
                            const [owner, repo, prNumber] = parts;
                            checkPrReviewExists(owner, repo, parseInt(prNumber));
                        }
                    }

                    // Stop polling if no active reviews
                    const hasRunning = data.reviews.some(r => r.status === 'running');
                    if (!hasRunning && reviewPollingInterval.value) {
                        clearInterval(reviewPollingInterval.value);
                        reviewPollingInterval.value = null;
                    }
                }
            } catch (err) {
                console.error('Failed to fetch reviews:', err);
            }
        };

        const startReview = async (pr, isFollowup = false, previousReviewId = null) => {
            if (!selectedRepo.value) return;

            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;
            const key = `${owner}/${repo}/${pr.number}`;

            // Check if already running
            if (activeReviews.value[key]?.status === 'running') {
                console.log('Review already running for this PR');
                return;
            }

            const reviewData = {
                number: pr.number,
                url: pr.url,
                owner: owner,
                repo: repo,
                title: pr.title,
                author: pr.user?.login,
                is_followup: isFollowup,
                previous_review_id: previousReviewId
            };

            try {
                const response = await fetch('/api/reviews', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(reviewData)
                });

                const data = await response.json();

                if (response.ok) {
                    activeReviews.value[key] = {
                        status: 'running',
                        startedAt: new Date().toISOString(),
                        reviewFile: data.review_file,
                        isFollowup: data.is_followup
                    };

                    // Start polling if not already polling
                    if (!reviewPollingInterval.value) {
                        reviewPollingInterval.value = setInterval(fetchReviews, 5000);
                    }
                } else {
                    console.error('Failed to start review:', data.error);
                    alert(`Failed to start review: ${data.error}`);
                }
            } catch (err) {
                console.error('Failed to start review:', err);
                alert('Failed to start review. Check console for details.');
            }
        };

        // Start a follow-up review for a PR
        const startFollowupReview = async (pr, previousReviewId = null) => {
            await startReview(pr, true, previousReviewId);
        };

        const cancelReview = async (pr) => {
            if (!selectedRepo.value) return;

            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;
            const key = `${owner}/${repo}/${pr.number}`;

            try {
                const response = await fetch(`/api/reviews/${owner}/${repo}/${pr.number}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    delete activeReviews.value[key];
                } else {
                    const error = await response.json();
                    console.error('Failed to cancel review:', error.error);
                }
            } catch (err) {
                console.error('Failed to cancel review:', err);
            }
        };

        const getReviewStatus = (prNumber) => {
            if (!selectedRepo.value) return null;
            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;
            const key = `${owner}/${repo}/${prNumber}`;
            return activeReviews.value[key]?.status || null;
        };

        const getReviewError = (prNumber) => {
            if (!selectedRepo.value) return null;
            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;
            const key = `${owner}/${repo}/${prNumber}`;
            const review = activeReviews.value[key];
            if (review) {
                return {
                    errorOutput: review.errorOutput,
                    exitCode: review.exitCode
                };
            }
            return null;
        };

        // Review History Methods
        const fetchReviewHistory = async () => {
            historyLoading.value = true;
            try {
                const params = new URLSearchParams();
                if (historyFilters.repo) params.append('repo', historyFilters.repo);
                if (historyFilters.author) params.append('author', historyFilters.author);
                if (historyFilters.search) params.append('search', historyFilters.search);
                params.append('limit', '50');

                const response = await fetch(`/api/review-history?${params}`);
                if (response.ok) {
                    const data = await response.json();
                    reviewHistory.value = data.reviews || [];
                }
            } catch (err) {
                console.error('Failed to fetch review history:', err);
            } finally {
                historyLoading.value = false;
            }
        };

        const viewReviewDetail = async (reviewId) => {
            try {
                const response = await fetch(`/api/review-history/${reviewId}`);
                if (response.ok) {
                    const data = await response.json();
                    reviewViewerContent.value = data.review;
                    showReviewViewer.value = true;
                }
            } catch (err) {
                console.error('Failed to fetch review details:', err);
            }
        };

        const closeReviewViewer = () => {
            showReviewViewer.value = false;
            reviewViewerContent.value = null;
            copySuccess.value = false;
        };

        const copyReviewContent = async () => {
            if (!reviewViewerContent.value?.content) return;

            try {
                await navigator.clipboard.writeText(reviewViewerContent.value.content);
                copySuccess.value = true;
                // Reset after 2 seconds
                setTimeout(() => {
                    copySuccess.value = false;
                }, 2000);
            } catch (err) {
                console.error('Failed to copy to clipboard:', err);
                // Fallback for older browsers
                const textArea = document.createElement('textarea');
                textArea.value = reviewViewerContent.value.content;
                textArea.style.position = 'fixed';
                textArea.style.left = '-999999px';
                document.body.appendChild(textArea);
                textArea.select();
                try {
                    document.execCommand('copy');
                    copySuccess.value = true;
                    setTimeout(() => {
                        copySuccess.value = false;
                    }, 2000);
                } catch (e) {
                    console.error('Fallback copy failed:', e);
                    alert('Failed to copy to clipboard');
                }
                document.body.removeChild(textArea);
            }
        };

        const checkPrReviewExists = async (owner, repo, prNumber) => {
            const key = `${owner}/${repo}/${prNumber}`;
            if (prReviewCache.value[key]) {
                return prReviewCache.value[key];
            }

            try {
                const response = await fetch(`/api/review-history/check/${owner}/${repo}/${prNumber}`);
                if (response.ok) {
                    const data = await response.json();
                    prReviewCache.value[key] = data;
                    return data;
                }
            } catch (err) {
                console.error('Failed to check PR review:', err);
            }
            return { has_review: false };
        };

        const getPrReviewInfo = (prNumber) => {
            if (!selectedRepo.value) return null;
            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;
            const key = `${owner}/${repo}/${prNumber}`;
            return prReviewCache.value[key] || null;
        };

        const hasExistingReview = (prNumber) => {
            const info = getPrReviewInfo(prNumber);
            return info?.has_review || false;
        };

        const getExistingReviewScore = (prNumber) => {
            const info = getPrReviewInfo(prNumber);
            return info?.latest_review?.score || null;
        };

        // Fetch review info for all PRs in the current list
        const fetchReviewInfoForPRs = async () => {
            if (!selectedRepo.value || !prs.value.length) return;

            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;

            // Fetch review info in parallel for all PRs
            const reviewPromises = prs.value.map(pr =>
                checkPrReviewExists(owner, repo, pr.number)
            );
            await Promise.all(reviewPromises);

            // Then check for new commits only for PRs that have reviews
            const newCommitsPromises = prs.value
                .filter(pr => {
                    const info = prReviewCache.value[`${owner}/${repo}/${pr.number}`];
                    return info?.has_review;
                })
                .map(pr => checkNewCommits(owner, repo, pr.number));
            await Promise.all(newCommitsPromises);
        };

        const formatReviewDate = (dateStr) => {
            if (!dateStr) return '';
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit'
            });
        };

        const getScoreClass = (score) => {
            if (score === null || score === undefined) return 'score-na';
            if (score >= 7) return 'score-high';
            if (score >= 4) return 'score-medium';
            return 'score-low';
        };

        // PR State Display Helpers
        const getPrStateClass = (state) => {
            if (!state) return 'pr-state-unknown';
            const s = state.toUpperCase();
            if (s === 'MERGED') return 'pr-state-merged';
            if (s === 'CLOSED') return 'pr-state-closed';
            if (s === 'OPEN') return 'pr-state-open';
            return 'pr-state-unknown';
        };

        const getPrStateLabel = (state) => {
            if (!state) return 'Unknown';
            const s = state.toUpperCase();
            if (s === 'MERGED') return 'Merged';
            if (s === 'CLOSED') return 'Closed';
            if (s === 'OPEN') return 'Open';
            return state;
        };

        // New Commits Detection Methods
        const checkNewCommits = async (owner, repo, prNumber) => {
            const key = `${owner}/${repo}/${prNumber}`;
            try {
                const response = await fetch(`/api/reviews/check-new-commits/${owner}/${repo}/${prNumber}`);
                if (response.ok) {
                    const data = await response.json();
                    newCommitsInfo.value[key] = data;
                    return data;
                }
            } catch (err) {
                console.error('Failed to check new commits:', err);
            }
            return { has_new_commits: false };
        };

        const getNewCommitsInfo = (prNumber) => {
            if (!selectedRepo.value) return null;
            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;
            const key = `${owner}/${repo}/${prNumber}`;
            return newCommitsInfo.value[key] || null;
        };

        const hasNewCommits = (prNumber) => {
            const info = getNewCommitsInfo(prNumber);
            return info?.has_new_commits || false;
        };

        // Inline Comments Posting Methods
        const postInlineComments = async (reviewId) => {
            if (postingInlineComments.value[reviewId]) return;

            postingInlineComments.value[reviewId] = true;
            try {
                const response = await fetch(`/api/reviews/${reviewId}/post-inline-comments`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                const data = await response.json();

                if (response.ok) {
                    // Update the cache to reflect posted status
                    Object.keys(prReviewCache.value).forEach(key => {
                        const cached = prReviewCache.value[key];
                        if (cached?.latest_review?.id === reviewId) {
                            cached.latest_review.inline_comments_posted = true;
                        }
                    });
                    alert(`Posted ${data.issues_posted} inline comment(s) to GitHub`);
                } else {
                    alert(`Failed to post inline comments: ${data.error}`);
                }
            } catch (err) {
                console.error('Failed to post inline comments:', err);
                alert('Failed to post inline comments. Check console for details.');
            } finally {
                postingInlineComments.value[reviewId] = false;
            }
        };

        const isPostingInlineComments = (reviewId) => {
            return postingInlineComments.value[reviewId] || false;
        };

        const canPostInlineComments = (prNumber) => {
            const info = getPrReviewInfo(prNumber);
            if (!info?.has_review) return false;
            // Can post if there's a review and inline comments haven't been posted yet
            return !info.latest_review?.inline_comments_posted;
        };

        const getLatestReviewId = (prNumber) => {
            const info = getPrReviewInfo(prNumber);
            return info?.latest_review?.id || null;
        };

        // Post inline comments for a merge queue item
        const postQueueItemInlineComments = async (item) => {
            if (!item.reviewId || postingInlineComments.value[item.reviewId]) return;

            postingInlineComments.value[item.reviewId] = true;
            try {
                const response = await fetch(`/api/reviews/${item.reviewId}/post-inline-comments`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                const data = await response.json();

                if (response.ok) {
                    // Update the queue item to reflect posted status
                    const queueItem = mergeQueue.value.find(
                        q => q.number === item.number && q.repo === item.repo
                    );
                    if (queueItem) {
                        queueItem.inlineCommentsPosted = true;
                    }
                    alert(`Posted ${data.issues_posted} inline comment(s) to GitHub`);
                } else {
                    alert(`Failed to post inline comments: ${data.error}`);
                }
            } catch (err) {
                console.error('Failed to post inline comments:', err);
                alert('Failed to post inline comments. Check console for details.');
            } finally {
                postingInlineComments.value[item.reviewId] = false;
            }
        };

        const isReviewRunning = (prNumber) => {
            return getReviewStatus(prNumber) === 'running';
        };

        const showReviewError = (pr) => {
            const error = getReviewError(pr.number);
            if (error) {
                openReviewErrorModal(pr.number, pr.title, error.errorOutput, error.exitCode);
            }
        };

        const handleReviewClick = (pr) => {
            const status = getReviewStatus(pr.number);
            if (status === 'running') {
                cancelReview(pr);
            } else if (status === 'failed') {
                showReviewError(pr);
            } else {
                startReview(pr);
            }
        };

        // Handle review for queue items (different data structure)
        const getQueueItemReviewStatus = (item) => {
            // item.repo is "owner/repo" format
            const key = `${item.repo}/${item.number}`;
            return activeReviews.value[key]?.status || null;
        };

        const startQueueItemReview = async (item) => {
            // item.repo is "owner/repo" format
            const [owner, repo] = item.repo.split('/');
            const key = `${owner}/${repo}/${item.number}`;

            // Check if already running
            if (activeReviews.value[key]?.status === 'running') {
                console.log('Review already running for this PR');
                return;
            }

            const reviewData = {
                number: item.number,
                url: item.url,
                owner: owner,
                repo: repo
            };

            try {
                const response = await fetch('/api/reviews', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(reviewData)
                });

                const data = await response.json();

                if (response.ok) {
                    activeReviews.value[key] = {
                        status: 'running',
                        startedAt: new Date().toISOString(),
                        reviewFile: data.review_file
                    };

                    // Start polling if not already polling
                    if (!reviewPollingInterval.value) {
                        reviewPollingInterval.value = setInterval(fetchReviews, 5000);
                    }
                } else {
                    console.error('Failed to start review:', data.error);
                    alert(`Failed to start review: ${data.error}`);
                }
            } catch (err) {
                console.error('Failed to start review:', err);
                alert('Failed to start review. Check console for details.');
            }
        };

        const cancelQueueItemReview = async (item) => {
            const [owner, repo] = item.repo.split('/');
            const key = `${owner}/${repo}/${item.number}`;

            try {
                const response = await fetch(`/api/reviews/${owner}/${repo}/${item.number}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    delete activeReviews.value[key];
                } else {
                    const error = await response.json();
                    console.error('Failed to cancel review:', error.error);
                }
            } catch (err) {
                console.error('Failed to cancel review:', err);
            }
        };

        const getQueueItemReviewError = (item) => {
            const key = `${item.repo}/${item.number}`;
            const review = activeReviews.value[key];
            if (review) {
                return {
                    errorOutput: review.errorOutput,
                    exitCode: review.exitCode
                };
            }
            return null;
        };

        const showQueueItemReviewError = (item) => {
            const error = getQueueItemReviewError(item);
            if (error) {
                openReviewErrorModal(item.number, item.title, error.errorOutput, error.exitCode);
            }
        };

        const handleQueueItemReviewClick = (item) => {
            const status = getQueueItemReviewStatus(item);
            if (status === 'running') {
                cancelQueueItemReview(item);
            } else if (status === 'failed') {
                showQueueItemReviewError(item);
            } else {
                startQueueItemReview(item);
            }
        };

        // Settings Persistence
        let saveSettingsTimeout = null;

        const loadSettings = async () => {
            try {
                const response = await fetch('/api/settings/filter_settings');
                if (response.ok) {
                    const data = await response.json();
                    if (data.value) {
                        const saved = data.value;

                        // Helper to restore filters after selections complete
                        const restoreFilters = () => {
                            if (saved.filters) {
                                Object.keys(saved.filters).forEach(key => {
                                    if (key in filters) {
                                        filters[key] = saved.filters[key];
                                    }
                                });
                            }
                        };

                        // Restore selected account and repo
                        if (saved.selectedAccountLogin) {
                            // Wait for accounts to load, then select
                            const checkAccounts = setInterval(() => {
                                if (!accountsLoading.value && accounts.value.length > 0) {
                                    clearInterval(checkAccounts);
                                    const account = accounts.value.find(a => a.login === saved.selectedAccountLogin);
                                    if (account) {
                                        selectAccount(account);
                                        // Wait for repos to load, then select
                                        if (saved.selectedRepoFullName) {
                                            const checkRepos = setInterval(() => {
                                                if (!reposLoading.value && repos.value.length > 0) {
                                                    clearInterval(checkRepos);
                                                    // Find repo by constructing full name from owner.login and name
                                                    const repo = repos.value.find(r =>
                                                        `${r.owner.login}/${r.name}` === saved.selectedRepoFullName
                                                    );
                                                    if (repo) {
                                                        selectRepo(repo);
                                                        // Restore filters AFTER repo selection (which triggers fetchPRs)
                                                        // Use nextTick to ensure it happens after Vue updates
                                                        nextTick(() => {
                                                            restoreFilters();
                                                            // Re-fetch PRs with restored filters
                                                            fetchPRs();
                                                        });
                                                    }
                                                }
                                            }, 100);
                                            // Clear after 10 seconds to prevent infinite loop
                                            setTimeout(() => clearInterval(checkRepos), 10000);
                                        } else {
                                            // No repo saved, just restore filters
                                            restoreFilters();
                                        }
                                    }
                                }
                            }, 100);
                            // Clear after 10 seconds to prevent infinite loop
                            setTimeout(() => clearInterval(checkAccounts), 10000);
                        } else {
                            // No account saved, just restore filters
                            restoreFilters();
                        }
                    }
                }
            } catch (err) {
                console.error('Failed to load settings:', err);
            }
        };

        const saveSettings = async () => {
            try {
                // Construct full repo name from owner.login and name
                const repoFullName = selectedRepo.value
                    ? `${selectedRepo.value.owner.login}/${selectedRepo.value.name}`
                    : null;
                const settings = {
                    filters: { ...filters },
                    selectedAccountLogin: selectedAccount.value?.login || null,
                    selectedRepoFullName: repoFullName
                };
                await fetch('/api/settings/filter_settings', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ value: settings })
                });
            } catch (err) {
                console.error('Failed to save settings:', err);
            }
        };

        const debouncedSaveSettings = () => {
            if (saveSettingsTimeout) {
                clearTimeout(saveSettingsTimeout);
            }
            saveSettingsTimeout = setTimeout(() => {
                saveSettings();
            }, 1000);  // Save after 1 second of inactivity
        };

        // Watch filters for changes and save
        watch(filters, () => {
            debouncedSaveSettings();
        }, { deep: true });

        // Watch selected account and repo changes
        watch([selectedAccount, selectedRepo], () => {
            debouncedSaveSettings();
        });

        // Initialize
        onMounted(() => {
            // Load theme preference
            const savedDarkMode = localStorage.getItem('darkMode');
            if (savedDarkMode !== null) {
                darkMode.value = savedDarkMode === 'true';
            }
            document.body.classList.toggle('dark-mode', darkMode.value);

            // Load saved filter settings
            loadSettings();

            // Fetch accounts
            fetchAccounts();

            // Fetch merge queue
            fetchMergeQueue();

            // Fetch active reviews
            fetchReviews();

            // Add click outside listener
            document.addEventListener('click', handleClickOutside);

            // Add keydown listener for Escape key
            document.addEventListener('keydown', handleKeydown);
        });

        return {
            // Theme
            darkMode,
            toggleTheme,

            // Accounts
            accounts,
            accountsLoading,
            selectedAccount,
            selectAccount,
            clearAccount,

            // Repositories
            repos,
            reposLoading,
            repoSearch,
            showRepoDropdown,
            selectedRepo,
            filteredRepos,
            filterRepos,
            selectRepo,
            clearRepo,

            // Filters
            filtersExpanded,
            activeFilterTab,
            filters,
            activeFiltersCount,
            contributors,
            labels,
            branches,
            milestones,
            teams,
            resetFilters,
            toggleLabel,
            toggleSearchIn,
            toggleReview,
            toggleStatus,
            toggleExcludeLabel,

            // Pull Requests
            prs,
            loading,
            error,
            fetchPRs,

            // View Toggle
            activeView,
            setActiveView,

            // Developer Stats
            statsLoading,
            developerStats,
            statsError,
            statsSortBy,
            statsSortDirection,
            statsLastUpdated,
            statsFromCache,
            statsRefreshing,
            statsStale,
            sortedDeveloperStats,
            fetchDeveloperStats,
            refreshDeveloperStats,
            formatStatsLastUpdated,
            sortStats,
            getMergeRate,
            formatNumber,

            // Description Modal
            descriptionModal,
            openDescriptionModal,
            closeDescriptionModal,
            renderMarkdown,

            // Helpers
            getStateClass,
            getStateIcon,
            getStateLabel,
            getReviewClass,
            getGhReviewLabel,
            getGhReviewTitle,
            getCiStatusLabel,
            getCiStatusTitle,
            formatDate,
            truncateBody,

            // Merge Queue
            mergeQueue,
            showQueuePanel,
            queueRefreshing,
            fetchMergeQueue,
            refreshMergeQueue,
            addToQueue,
            removeFromQueue,
            isInQueue,
            toggleQueuePanel,
            closeQueuePanel,
            moveQueueItem,
            clearQueue,

            // Queue Notes
            queueNotes,
            notesLoading,
            openNotesDropdowns,
            selectedNoteIndex,
            notesModal,
            getQueueKey,
            getNotesCount,
            getItemNotes,
            fetchNotesForQueueItem,
            toggleNotesDropdown,
            isNotesDropdownOpen,
            selectNote,
            getSelectedNote,
            openNotesModal,
            closeNotesModal,
            saveNote,
            deleteNote,
            truncateNote,
            formatNoteDate,

            // Code Reviews
            activeReviews,
            fetchReviews,
            startReview,
            startFollowupReview,
            cancelReview,
            getReviewStatus,
            getReviewError,
            isReviewRunning,
            handleReviewClick,
            showReviewError,
            getQueueItemReviewStatus,
            handleQueueItemReviewClick,
            reviewErrorModal,
            openReviewErrorModal,
            closeReviewErrorModal,

            // Review History
            reviewHistory,
            historyLoading,
            historyFilters,
            selectedHistoryReview,
            showHistoryPanel,
            showReviewViewer,
            reviewViewerContent,
            copySuccess,
            prReviewCache,
            fetchReviewHistory,
            viewReviewDetail,
            closeReviewViewer,
            copyReviewContent,
            checkPrReviewExists,
            getPrReviewInfo,
            hasExistingReview,
            getExistingReviewScore,
            fetchReviewInfoForPRs,
            formatReviewDate,
            getScoreClass,

            // PR State Display
            getPrStateClass,
            getPrStateLabel,

            // New Commits Detection
            newCommitsInfo,
            checkNewCommits,
            getNewCommitsInfo,
            hasNewCommits,

            // Inline Comments Posting
            postingInlineComments,
            postInlineComments,
            postQueueItemInlineComments,
            isPostingInlineComments,
            canPostInlineComments,
            getLatestReviewId,

            // Settings Persistence
            loadSettings,
            saveSettings
        };
    }
}).mount('#app');
