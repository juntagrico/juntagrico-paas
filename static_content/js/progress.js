$(function () {
    let current_url = url
    let current_step = 0
    let expected_steps = 5

    function wait_for_pid() {
        $.getJSON(current_url, function( data ) {
            if(data.status!="zombie"){
                // update title
                $("#progress-text").text(data.current_title)
                // calculate progress
                current_step += data.section
                let num_value = (current_step + data.section_progress) / expected_steps
                // set progress
                $("#progress").attr("aria-valuenow", num_value);
                var perc=num_value+"%";
                $("#progress").css("width",perc)
                // poll progress
                current_url = url + '?s=' + data.read
                setTimeout(wait_for_pid,1000);
            }
            else{
                $("#progress-div").hide();
                $( "#next" ).removeClass( "disabled" );
            }
        }).fail(function() {
            $("#progress").removeClass("progress-bar-animated bg-success").addClass("bg-error")
        });
    }
    
    wait_for_pid();
    
});
