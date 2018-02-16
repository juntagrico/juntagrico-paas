/*global define*/
define([], function () {

    function wait_for_pid(){
        $.getJSON( "/pid/"+pid+"/", function( data ) {
            alert(data);
            var result = JSON.parse(data);
            if(result.status!="zombie"){
                setTimeout(wait_for_pid,1000) ;
            }
            else{
                $( "#next" ).removeClass( "disabled" );
            }
        });
    }
    
    wait_for_pid();
    
});