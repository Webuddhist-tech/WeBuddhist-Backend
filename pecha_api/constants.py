
class Constants:

    QUERY_BATCH_SIZE=100
    MINUTE_IN_SECONDS = 60
    HOUR_IN_SECONDS = 3600
    DAY_IN_SECONDS = 86400
    WEEK_IN_SECONDS = 604800
    MONTH_IN_SECONDS = 2592000
    YEAR_IN_SECONDS = 31536000

    # Image hosts an avatar may point at without living in our bucket. These
    # are the identity providers' own CDNs, where Auth0's `picture` claim
    # points; a match is on the host itself or a subdomain of it.
    SOCIAL_PICTURE_HOSTS = (
        "googleusercontent.com",
        "gravatar.com",
        "auth0.com",
        "fbcdn.net",
        "graph.facebook.com",
        "cdn-apple.com",
    )


    LANGUAGE_NUMBER = {
        "bo": {
            "0": "༠",
            "1": "༡",
            "2": "༢",
            "3": "༣",
            "4": "༤",
            "5": "༥",
            "6": "༦",
            "7": "༧",
            "8": "༨",
            "9": "༩"
        },
        "en": {
            "0": "0",
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
            "5": "5",
            "6": "6",
            "7": "7",
            "8": "8",
            "9": "9"
        }

    }

    TIME_PASSED_NOW = {
        "Now" : {
            "en": "Now",
            "bo": "དད་ལྟ།"
        },
        "Min": {
            "en": "Min",
            "bo": "སྐར་མ།"
        },
        "Hr": {
            "en": "Hr",
            "bo": "ཆུ་ཚོད།"
        },
        "Day": {
            "en": "Day",
            "bo": "ཉིནམ།"
        },
        "Week": {
            "en": "Week",
            "bo": "གཟའ་འཁོར།"
        },
        "Month": {
            "en": "Month",
            "bo": "ཟླ་བ།"
        },
        "Year": {
            "en": "Year",
            "bo": "ལོ།"
        }
    }

    excluded_text_ids = []

    INSTANCE_TYPE="critical"
    TEXT_TYPE = "root"