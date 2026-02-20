$(function () {
    let current_url = url

    function wait_for_pid() {
        $.getJSON(current_url, function( data ) {
            if(data.status!="zombie"){
                var num_value = parseInt($("#progress").attr("aria-valuenow"));
                num_value+=4;
                if(num_value>100){
                    num_value=1;
                }
                $("#progress").attr("aria-valuenow", num_value);
                var perc=num_value+"%";
                $("#progress").css("width",perc)
                current_url = url + '?s=' + data.read
                setTimeout(wait_for_pid,1000);
            }
            else{
                $("#progress-div").hide();
                $( "#next" ).removeClass( "disabled" );
            }
        });
    }
    
    wait_for_pid();
    
});
