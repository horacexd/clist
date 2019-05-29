filterTimeoutUpdate = 2000

function filterCallback(value) {
    calendar.refetchEvents()
}

$(function() {
    function get_calendar_height() {
        return $(window).height() - 200;
    }

    $(window).resize(function() {
        calendar.setOption('height', get_calendar_height())
    });

    calendar = new FullCalendar.Calendar($('#calendar')[0], {
        plugins: ['dayGrid', 'timeGrid', 'list'],
        header: {
            left: 'title',
            center: '',
            right: 'today dayGridMonth,timeGridWeek,listWeek prev,next'
        },
        firstDay: 1,
        timezone: timezone,
        events: {
            url: '/get/events/',
            method: 'GET',
            extraParams: function() {
                var hide = []
                $('.ignore-filters')
                    .filter(function () { return $(this).attr('data-value') == '1' })
                    .each(function () { hide.push($(this).attr('data-id')) })
                return {
                    'cs': ['calendar'],
                    'if': hide,
                    'f': $('#filter [type="text"]').val()
                }
            }
        },
        eventRender: function (info) {
            var event = info.event
            var element = info.el
            console.log(event)
            $(element).tooltip({
                placement: 'top',
                container: 'body',
                html: true,
                delay: {
                    'show': 300,
                    'hide': 100,
                },
                title:
                    event.title +
                    '</br>Start: ' + event.start +
                    (event.end? '</br>End: ' + event.end : '')
            })
        },
        eventClick: function (data, event, view) {
            return true
        },
        loading: function(bool) {
            $('#loading').toggle(bool);
        },
        eventLimit: true,
        height: get_calendar_height()
    })

    calendar.render()


    $('.ignore-filters').click(function (e) {
        var $btn = $(this)
        var value = $btn.attr('data-value')
        $btn.attr('data-value', 1 - value)
        $btn.css('background-color', value == '0'? '#5BC0DE' : '#fff')
        calendar.refetchEvents()
        e.preventDefault()
        return false
    })
});