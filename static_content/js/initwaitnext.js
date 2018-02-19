/*global define*/
define([], function () {

    function wait_for_pid(){
        $.getJSON( "/pid/"+pid+"/", function( data ) {
            if(data.status!="zombie"){
                var num_value = $("#progress").attr("aria-valuenow");
                num_value++
                if(num_value>100){
                    num_value=1;
                }
                $("#progress").attr("aria-valuenow", num_value);
                setTimeout(wait_for_pid,1000) ;
            }
            else{
                $("#progress").hide();
                $( "#next" ).removeClass( "disabled" );
            }
        });
    }
    
    wait_for_pid();
    
});