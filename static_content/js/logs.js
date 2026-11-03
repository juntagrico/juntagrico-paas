$(document).ready(function() {
    var $tbody = $('#log-tbody');
    var $entries = $('.log-entry');
    var $filterBtns = $('.log-filter-btn');
    var $searchInput = $('#log-search');
    var $sortToggle = $('#sort-toggle');
    var $sortLabel = $('#sort-label');

    var activeLevel = 'all';
    var searchQuery = '';
    var newestFirst = true;

    function filterLogs() {
        $entries.each(function() {
            var $entry = $(this);
            var level = $entry.data('level');
            var text = $entry.text().toLowerCase();

            var levelMatch = (activeLevel === 'all' || level === activeLevel);
            var searchMatch = (!searchQuery || text.indexOf(searchQuery) !== -1);

            if (levelMatch && searchMatch) {
                $entry.show();
            } else {
                $entry.hide();
            }
        });
    }

    function reorderLogs() {
        var rows = $tbody.find('.log-entry').detach();
        // Docker returns oldest-first; reverse when newestFirst is true
        if (newestFirst) {
            rows = rows.get().reverse();
        }
        $tbody.append(rows);
    }

    $filterBtns.on('click', function() {
        $filterBtns.removeClass('active btn-primary').addClass('btn-outline-secondary');
        $(this).removeClass('btn-outline-secondary').addClass('active btn-primary');
        activeLevel = $(this).data('level');
        filterLogs();
    });

    $searchInput.on('input', function() {
        searchQuery = $(this).val().toLowerCase();
        filterLogs();
    });

    $sortToggle.on('click', function() {
        newestFirst = !newestFirst;
        $sortLabel.text(newestFirst ? 'Newest first' : 'Oldest first');
        reorderLogs();
    });

    // Reorder on page load (Docker returns oldest first)
    reorderLogs();
});
