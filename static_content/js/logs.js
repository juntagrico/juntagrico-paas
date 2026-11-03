$(document).ready(function() {
    var $entries = $('.log-entry');
    var $filterBtns = $('.log-filter-btn');
    var $searchInput = $('#log-search');

    var activeLevel = 'all';
    var searchQuery = '';

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

    // Set initial active button style
    $filterBtns.first().removeClass('btn-outline-secondary').addClass('btn-primary');
});
