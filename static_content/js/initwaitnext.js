/*global define*/
define([], function () {

    function wait_for_pid(){
        $.getJSON( "/pid/"+pid+"/", function( data ) {
            if(data.status!="zombie"){
                setTimeout(wait_for_pid,1000) ;
            }
            else{
                $( "#next" ).removeClass( "disabled" );
            }
        });
    }
    
    wait_for_pid();
    
});