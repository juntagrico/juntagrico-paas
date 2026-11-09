$(function () {
    let current_url = url
    let current_step = 0
    let last_section_progress = 0
    let expected_steps = 6.1
    let setupSuccess = undefined

    function set_progress(value) {
        let bar = $("#progress")
        bar.attr("aria-valuenow", value);
        bar.css("width", value + "%")
        if (value >= 100) {
            bar.removeClass("progress-bar-animated")
        }
    }

    function wait_for_pid() {
        $.getJSON(current_url, function (data) {
            if (data.expected_steps) {
                expected_steps = data.expected_steps
            }

            // Track setup_success on every poll so it persists even if the last
            // finished=True response doesn't include it
            if (data.setup_success !== undefined) {
                setupSuccess = data.setup_success
            }

            if (!(data.finished)) {
                // update title
                if (data.title !== null) {
                    $("#progress-text").text(data.title)
                }
                // calculate progress
                current_step += data.section
                if (data.section_progress !== null) {
                    last_section_progress = data.section_progress
                }
                let num_value = (current_step + last_section_progress) / expected_steps * 100
                // set progress
                set_progress(num_value)
                // poll progress, preserving existing query params (e.g. copy_data)
                let base = url.split('?')[0]
                let params = new URLSearchParams(url.split('?')[1] || '')
                params.set('s', data.read)
                current_url = base + '?' + params.toString()
                setTimeout(wait_for_pid, 1000);
            } else {
                $("#progress-title").text("Fertig!")
                $("#progress-text").text("")
                set_progress(100)

                // Setup mode: use the stored setupSuccess value (may have arrived before finished=True)
                if ($("#setup-result").length) {
                    if (setupSuccess === true && adminPassword) {
                        $("#next").removeClass("disabled")
                        $("#setup-result").show()
                    } else {
                        // On failure, redirect to show_result to display the full log
                        window.location.href = showResultUrl
                    }
                } else {
                    $( "#next" ).removeClass( "disabled" );
                }
            }
        }).fail(function () {
            $("#progress").removeClass("progress-bar-animated bg-success").addClass("bg-error")
        });
    }

    wait_for_pid();

});
