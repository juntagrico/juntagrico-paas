$(function () {
    let current_url = url
    let current_step = 0
    let last_section_progress = 0
    let expected_steps = 5.1

    function set_progress(value) {
        let bar = $("#progress")
        bar.attr("aria-valuenow", value);
        bar.css("width", value + "%")
        if (value>=100) {
            bar.removeClass("progress-bar-animated")
        }
    }

    function wait_for_pid() {
        $.getJSON(current_url, function( data ) {
            if(data.status!="zombie"){
                // update title
                if (data.title!==null) {
                    $("#progress-text").text(data.title)
                }
                // calculate progress
                current_step += data.section
                if (data.section_progress!==null) {
                    last_section_progress = data.section_progress
                }
                let num_value = (current_step + last_section_progress) / expected_steps * 100
                // set progress
                set_progress(num_value)
                // poll progress
                current_url = url + '?s=' + data.read
                setTimeout(wait_for_pid,1000);
            }
            else{
                $("#progress-title").text("Fertig!")
                $("#progress-text").text("")
                set_progress(100)
                $( "#next" ).removeClass( "disabled" );
            }
        }).fail(function() {
            $("#progress").removeClass("progress-bar-animated bg-success").addClass("bg-error")
        });
    }
    
    wait_for_pid();
    
});
