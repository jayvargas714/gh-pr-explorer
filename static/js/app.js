/**
 * GitHub PR Explorer - Vue.js Application
 * A lightweight web application to browse, filter, and explore GitHub Pull Requests
 */

const { createApp, ref, reactive, computed, watch, onMounted } = Vue;

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

        // Description Modal
        const descriptionModal = reactive({
            show: false,
            pr: null
        });

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
            } catch (err) {
                error.value = err.message || 'Failed to fetch pull requests';
                console.error('Failed to fetch PRs:', err);
            } finally {
                loading.value = false;
            }
        };

        const fetchDeveloperStats = async () => {
            if (!selectedRepo.value) return;

            statsLoading.value = true;
            statsError.value = null;

            const owner = selectedRepo.value.owner.login;
            const repo = selectedRepo.value.name;

            try {
                const response = await fetch(`/api/repos/${owner}/${repo}/stats`);
                const data = await response.json();

                if (data.error) {
                    throw new Error(data.error);
                }

                developerStats.value = data.stats || [];
            } catch (err) {
                statsError.value = err.message || 'Failed to fetch developer stats';
                console.error('Failed to fetch stats:', err);
            } finally {
                statsLoading.value = false;
            }
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

        const formatDate = (dateString) => {
            if (!dateString) return '';
            const date = new Date(dateString);
            const now = new Date();
            const diffMs = now - date;
            const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

            if (diffDays === 0) {
                const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
                if (diffHours === 0) {
                    const diffMins = Math.floor(diffMs / (1000 * 60));
                    return `${diffMins}m ago`;
                }
                return `${diffHours}h ago`;
            }
            if (diffDays === 1) return 'yesterday';
            if (diffDays < 7) return `${diffDays}d ago`;
            if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
            if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
            return `${Math.floor(diffDays / 365)}y ago`;
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

        // Initialize
        onMounted(() => {
            // Load theme preference
            const savedDarkMode = localStorage.getItem('darkMode');
            if (savedDarkMode !== null) {
                darkMode.value = savedDarkMode === 'true';
            }
            document.body.classList.toggle('dark-mode', darkMode.value);

            // Fetch accounts
            fetchAccounts();

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
            sortedDeveloperStats,
            fetchDeveloperStats,
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
            formatDate,
            truncateBody
        };
    }
}).mount('#app');
