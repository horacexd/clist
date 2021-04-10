<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $types = array('upcoming', 'active', 'past');

    foreach ($types as $type) {
        $limit = 100;
        $url = 'https://dphi.tech/api/datathons/?list=' . $type . '&page=1&page_size=' . $limit . '&query=%7Bid,challenge,end_date,datathon_type,start_date,title,slug,url%7D';
        while ($url) {
            $response = curlexec($url, null, array("http_header" => array('content-type: application/json'), "json_output" => 1));

            foreach ($response['results'] as $c) {
                if (!preg_match('#(?P<id>[0-9]+)/?$#', $c['challenge'], $match)) {
                    continue;
                }
                $cid = $match['id'];

                $title = $c['title'] . '. ' . ucfirst($c['datathon_type']);
                $contests[] = array(
                    'start_time' => $c['start_date'],
                    'end_time' => $c['end_date'],
                    'title' => $title,
                    'url' => url_merge($URL, "/challenges/${c['slug']}/$cid/"),
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $cid,
                );
            }

            if ($type == 'past' && !isset($_GET['parse_full_list'])) {
                break;
            }

            $url = $response['next'];
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
