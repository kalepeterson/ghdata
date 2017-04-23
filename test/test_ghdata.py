import os
import pytest
import pandas

@pytest.fixture
def gh():
    import ghdata
    return ghdata.GHData(os.getenv("DB_TEST_URL"))

def test_repoid(gh):
    assert gh.repoid('rails', 'rails') == 78852

def test_userid(gh):
    assert gh.userid('howderek') == 417486

"""
Pandas testing format

assert gh.<function>(gh.repoid('owner', 'repo')).isin(['<data that should be in dataframe>']).any

The tests check if a value is anywhere in the dataframe
"""
def test_stargazers(gh):
    assert gh.stargazers(gh.repoid('akka', 'akka')).isin(["2011-09-14"]).any

def test_commits(gh):
    assert gh.commits(gh.repoid('facebook', 'folly')).isin(["2013-01-07"]).any

def test_forks(gh):
    assert gh.forks(gh.repoid('facebook', 'hiphop-php')).isin(["2012-01-08"]).any

def test_issues(gh):
    assert gh.issues(gh.repoid('mongodb', 'mongo')).isin(["2013-01-05"]).any

def test_issues_with_close(gh):
    assert gh.issues_with_close(gh.repoid('TrinityCore', 'TrinityCore')).isin(["2012-01-08"]).any

def test_contributors(gh):
    assert gh.contributors(gh.repoid('TTimo', 'doom3.gpl')).isin(["sergiocampama"]).any

def test_contributions(gh):
    assert gh.contributions(gh.repoid('ariya', 'phantomjs')).isin(["ariya"]).any

def test_committer_locations(gh):
    assert gh.committer_locations(gh.repoid('mavam', 'stat-cookbook')).isin(["Berkeley, CA"]).any

def test_issue_response_time(gh):
    assert gh.issue_response_time(gh.repoid('hadley', 'devtools')).isin(["2013-09-16 17:00:54"]).any

def test_linking_websites(gh):
    assert gh.linking_websites(gh.repoid('yihui', 'knitr')).isin(["sohu.com"]).any

def test_pull_acceptance_rate(gh):
    assert gh.pull_acceptance_rate(gh.repoid('akka', 'akka')).isin([0.5]).any

# ----- Added tests -----

def test_stargazers_grouped_year(gh):
    assert gh.stargazers_grouped(gh.repoid('rstudio', 'shiny'), 'year').isin(["331"]).any
    assert gh.stargazers_grouped(gh.repoid('rstudio', 'shiny'), 'y').isin(["331"]).any

def test_stargazers_grouped_month(gh):
    assert gh.stargazers_grouped(gh.repoid('rstudio', 'shiny'), 'month').isin(["331"]).any
    assert gh.stargazers_grouped(gh.repoid('rstudio', 'shiny'), 'm').isin(["331"]).any

def test_stargazers_grouped_week(gh):
    assert gh.stargazers_grouped(gh.repoid('rstudio', 'shiny'), 'week').isin(["331"]).any
    assert gh.stargazers_grouped(gh.repoid('rstudio', 'shiny'), 'w').isin(["331"]).any

def test_stargazers_grouped_day(gh):
    assert gh.stargazers_grouped(gh.repoid('rstudio', 'shiny'), 'day').isin(["331"]).any
    assert gh.stargazers_grouped(gh.repoid('rstudio', 'shiny'), 'd').isin(["331"]).any

def test_forks_grouped(gh):
    assert gh.forks_grouped(gh.repoid('rstudio', 'shiny'), 'year').isin(["331"]).any

def test_forks_grouped_default(gh):
    assert gh.forks_grouped_default(gh.repoid('rstudio', 'shiny')).isin(["331"]).any

def test_pulls_grouped(gh):
    assert gh.pulls_grouped(gh.repoid('rstudio', 'shiny'), 'year').isin(["331"]).any

def test_issue_actions(gh):
    assert gh.issue_actions(gh.repoid('rstudio', 'shiny')).isin(["331"]).any

# -- Added Milestone 3 Tests --
def test_average_issue_response(gh):
    assert gh.average_issue_response_time(gh.repoid('rstudio', 'shiny')).isin(["331"]).any

def test_relative_activity(gh):
    assert gh.relative_activity(gh.repoid('rstudio', 'shiny')).isin(["331"]).any

def test_relative_activity_pm(gh):
    assert gh.relative_activity_pm(gh.repoid('rstudio', 'shiny')).isin(["331"]).any

def test_relative_activity_nonpm(gh):
    assert gh.relative_activity_nonpm(gh.repoid('rstudio', 'shiny')).isin(["331"]).any