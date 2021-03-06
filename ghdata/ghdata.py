#SPDX-License-Identifier: MIT

import sqlalchemy as s
import pandas as pd
import requests
import sys
if (sys.version_info > (3, 0)):
    import urllib.parse as url
else:
    import urllib as url
import json
import re

class GHData(object):

    """Uses GHTorrent and other GitHub data sources and returns dataframes with interesting GitHub indicators"""

    def __init__(self, dbstr, public_www_api_key=None):
        """
        Connect to GHTorrent
t
        :param dbstr: The [database string](http://docs.sqlalchemy.org/en/latest/core/engines.html) to connect to the GHTorrent database
        """
        self.db = s.create_engine(dbstr)
        self.PUBLIC_WWW_API_KEY = public_www_api_key

    def convert_group_type(self, group_type):
        group_types = {'DAY', 'WEEK', 'MONTH', 'YEAR'}
        gt_shortcut = {'D': 'DAY', 'W': 'WEEK', 'M': 'MONTH', 'Y': 'YEAR'}
        if not group_type in group_types:
            if group_type in gt_shortcut.keys():
                group_type = gt_shortcut[group_type]
            else:
                group_type = 'WEEK'
        return group_type

    def __single_table_count_by_date(self, table, repo_col='project_id', group_type='WEEK'):
        """
        Generates query string to count occurances of rows per date for a given table.
        External input must never be sent to this function, it is for internal use only.

        :param table: The table in GHTorrent to generate the string for
        :param repo_col: The column in that table with the project ids
        :param group_type: Member of GROUP_TYPES, determines grouping granularity
        :return: Query string
        """
        gt = group_type.upper()
        return """
            SELECT date(created_at) AS "date", COUNT(*) AS "{0}"
            FROM {0}
            WHERE {1} = :repoid
            GROUP BY {2}(created_at)""".format(table, repo_col, self.convert_group_type(gt))

    def repoid(self, owner, repo):
        """
        Returns a repository's ID as it appears in the GHTorrent projects table
        github.com/[owner]/[project]

        :param owner: The username of a project's owner
        :param repo: The name of the repository
        :return: The repository's ID as it appears in the GHTorrent projects table
        """
        reposql = s.sql.text('SELECT projects.id FROM projects INNER JOIN users ON projects.owner_id = users.id WHERE projects.name = :repo AND users.login = :owner')
        repoid = 0
        result = self.db.execute(reposql, repo=repo, owner=owner)
        for row in result:
            repoid = row[0]
        return repoid

    def userid(self, username):
        """
        Returns the userid given a username

        :param username: GitHub username to be matched against the login table in GHTorrent
        :return: The id from the users table in GHTorrent
        """
        reposql = s.sql.text('SELECT users.id FROM users WHERE users.login = :username')
        userid = 0
        result = self.db.execute(reposql, username=username)
        for row in result:
            userid = row[0]
        return userid


    # Basic timeseries queries
    def stargazers(self, repoid, start=None, end=None):
        """
        Timeseries of when people starred a repo

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with stargazers/day
        """
        stargazersSQL = s.sql.text(self.__single_table_count_by_date('watchers', 'repo_id'))
        return pd.read_sql(stargazersSQL, self.db, params={"repoid": str(repoid)})

    def commits(self, repoid):
        """
        Timeseries of all the commits on a repo

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with commits/day
        """
        commitsSQL = s.sql.text(self.__single_table_count_by_date('commits'))
        return pd.read_sql(commitsSQL, self.db, params={"repoid": str(repoid)})

    def forks_grouped(self, repoid, group_type):
        """
        Timeseries of when a repo's forks were created

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :param group_type: Key of member of GROUP_TYPES, otherwise defaults to WEEK on failed lookup
        :return: DataFrame with count of forks created grouped by group_type, i.e. year, month, week, or day.
        """
        forksSQL = s.sql.text(self.__single_table_count_by_date('projects', 'forked_from', group_type))
        return pd.read_sql(forksSQL, self.db, params={"repoid": str(repoid)})

    def issues(self, repoid):
        """
        Timeseries of when people starred a repo

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with issues/day
        """
        issuesSQL = s.sql.text(self.__single_table_count_by_date('issues', 'repo_id'))
        return pd.read_sql(issuesSQL, self.db, params={"repoid": str(repoid)})

    def issues_with_close(self, repoid):
        """
        How long on average each week it takes to close an issue

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with issues/day
        """
        issuesSQL = s.sql.text("""
            SELECT issues.id as "id",
                   issues.created_at as "date",
                   DATEDIFF(closed.created_at, issues.created_at)  AS "days_to_close"
            FROM issues

           JOIN
                (SELECT * FROM issue_events
                 WHERE issue_events.action = "closed") closed
            ON issues.id = closed.issue_id

            WHERE issues.repo_id = :repoid""")
        return pd.read_sql(issuesSQL, self.db, params={"repoid": str(repoid)})

    def pulls(self, repoid):
        """
        Timeseries of pull requests creation, also gives their associated activity

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with pull requests by day
        """
        pullsSQL = s.sql.text("""
            SELECT date(pull_request_history.created_at) AS "date",
            (COUNT(pull_requests.id)) AS "pull_requests",
            (SELECT COUNT(*) FROM pull_request_comments
            WHERE pull_request_comments.pull_request_id = pull_request_history.pull_request_id) AS "comments"
            FROM pull_request_history
            INNER JOIN pull_requests
            ON pull_request_history.pull_request_id = pull_requests.id
            WHERE pull_requests.head_repo_id = :repoid
            AND pull_request_history.action = "merged"
            GROUP BY WEEK(pull_request_history.created_at)
        """)
        return pd.read_sql(pullsSQL, self.db, params={"repoid": str(repoid)})

    def contributors(self, repoid):
        """
        All the contributors to a project and the counts of their contributions

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with users id, users login, and their contributions by type
        """
        contributorsSQL = s.sql.text("""
            SELECT * FROM

               (
               SELECT   users.id        as "user_id",
                        users.login     as "login",
                        users.location  as "location",
                        com.count       as "commits",
                        pulls.count     as "pull_requests",
                        iss.count       as "issues",
                        comcoms.count   as "commit_comments",
                        pullscoms.count as "pull_request_comments",
                        isscoms.count   as "issue_comments",
                        com.count + pulls.count + iss.count + comcoms.count + pullscoms.count + isscoms.count as "total"

               FROM users

               LEFT JOIN (SELECT committer_id AS id, COUNT(*) AS count FROM commits INNER JOIN project_commits ON project_commits.commit_id = commits.id WHERE project_commits.project_id = :repoid GROUP BY commits.committer_id) AS com
               ON com.id = users.id

               LEFT JOIN (SELECT pull_request_history.actor_id AS id, COUNT(*) AS count FROM pull_request_history JOIN pull_requests ON pull_requests.id = pull_request_history.pull_request_id WHERE pull_requests.base_repo_id = :repoid AND pull_request_history.action = 'merged' GROUP BY pull_request_history.actor_id) AS pulls
               ON pulls.id = users.id

               LEFT JOIN (SELECT reporter_id AS id, COUNT(*) AS count FROM issues WHERE issues.repo_id = :repoid GROUP BY issues.reporter_id) AS iss
               ON iss.id = users.id

               LEFT JOIN (SELECT commit_comments.user_id AS id, COUNT(*) AS count FROM commit_comments JOIN project_commits ON project_commits.commit_id = commit_comments.commit_id WHERE project_commits.project_id = :repoid GROUP BY commit_comments.user_id) AS comcoms
               ON comcoms.id = users.id

               LEFT JOIN (SELECT pull_request_comments.user_id AS id, COUNT(*) AS count FROM pull_request_comments JOIN pull_requests ON pull_request_comments.pull_request_id = pull_requests.id WHERE pull_requests.base_repo_id = :repoid GROUP BY pull_request_comments.user_id) AS pullscoms
               ON pullscoms.id = users.id

               LEFT JOIN (SELECT issue_comments.user_id AS id, COUNT(*) AS count FROM issue_comments JOIN issues ON issue_comments.issue_id = issues.id WHERE issues.repo_id = :repoid GROUP BY issue_comments.user_id) AS isscoms
               ON isscoms.id = users.id

               GROUP BY users.id
               ORDER BY com.count DESC
               ) user_activity

            WHERE commits IS NOT NULL
            OR    pull_requests IS NOT NULL
            OR    issues IS NOT NULL
            OR    commit_comments IS NOT NULL
            OR    pull_request_comments IS NOT NULL
            OR    issue_comments IS NOT NULL;
        """)
        return pd.read_sql(contributorsSQL, self.db, index_col=['user_id'], params={"repoid": str(repoid)})


    def contributions(self, repoid, userid=None):
        """
        Timeseries of all the contributions to a project, optionally limited to a specific user

        :param repoid: The id of the project in the projects table.
        :param userid: The id of user if you want to limit the contributions to a specific user.
        :return: DataFrame with all of the contributions seperated by day.
        """
        rawContributionsSQL = """
            SELECT  DATE(coms.created_at) as "date",
                    coms.count            as "commits",
                    pulls.count           as "pull_requests",
                    iss.count             as "issues",
                    comcoms.count         as "commit_comments",
                    pullscoms.count       as "pull_request_comments",
                    isscoms.count         as "issue_comments",
                    coms.count + pulls.count + iss.count + comcoms.count + pullscoms.count + isscoms.count as "total"

            FROM (SELECT created_at AS created_at, COUNT(*) AS count FROM commits INNER JOIN project_commits ON project_commits.commit_id = commits.id WHERE project_commits.project_id = :repoid[[ AND commits.author_id = :userid]] GROUP BY DATE(created_at)) coms

            LEFT JOIN (SELECT pull_request_history.created_at AS created_at, COUNT(*) AS count FROM pull_request_history JOIN pull_requests ON pull_requests.id = pull_request_history.pull_request_id WHERE pull_requests.base_repo_id = :repoid AND pull_request_history.action = 'merged'[[ AND pull_request_history.actor_id = :userid]] GROUP BY DATE(created_at)) AS pulls
            ON DATE(pulls.created_at) = DATE(coms.created_at)

            LEFT JOIN (SELECT issues.created_at AS created_at, COUNT(*) AS count FROM issues WHERE issues.repo_id = :repoid[[ AND issues.reporter_id = :userid]] GROUP BY DATE(created_at)) AS iss
            ON DATE(iss.created_at) = DATE(coms.created_at)

            LEFT JOIN (SELECT commit_comments.created_at AS created_at, COUNT(*) AS count FROM commit_comments JOIN project_commits ON project_commits.commit_id = commit_comments.commit_id WHERE project_commits.project_id = :repoid[[ AND commit_comments.user_id = :userid]] GROUP BY DATE(commit_comments.created_at)) AS comcoms
            ON DATE(comcoms.created_at) = DATE(coms.created_at)

            LEFT JOIN (SELECT pull_request_comments.created_at AS created_at, COUNT(*) AS count FROM pull_request_comments JOIN pull_requests ON pull_request_comments.pull_request_id = pull_requests.id WHERE pull_requests.base_repo_id = :repoid[[ AND pull_request_comments.user_id = :userid]] GROUP BY DATE(pull_request_comments.created_at)) AS pullscoms
            ON DATE(pullscoms.created_at) = DATE(coms.created_at)

            LEFT JOIN (SELECT issue_comments.created_at AS created_at, COUNT(*) AS count FROM issue_comments JOIN issues ON issue_comments.issue_id = issues.id WHERE issues.repo_id = :repoid[[ AND issue_comments.user_id = :userid]] GROUP BY DATE(issue_comments.created_at)) AS isscoms
            ON DATE(isscoms.created_at) = DATE(coms.created_at)

            ORDER BY DATE(coms.created_at)
        """

        if (userid is not None and len(userid) > 0):
            rawContributionsSQL = rawContributionsSQL.replace('[[', '')
            rawContributionsSQL = rawContributionsSQL.replace(']]', '')
            parameterized = s.sql.text(rawContributionsSQL)
            return pd.read_sql(parameterized, self.db, params={"repoid": str(repoid), "userid": str(userid)})
        else:
            rawContributionsSQL = re.sub(r'\[\[.+?\]\]', '', rawContributionsSQL)
            parameterized = s.sql.text(rawContributionsSQL)
            return pd.read_sql(parameterized, self.db, params={"repoid": str(repoid)})

    def committer_locations(self, repoid):
        """
        Return committers and their locations

        @todo: Group by country code instead of users, needs the new schema

        :param repoid: The id of the project in the projects table.
        :return: DataFrame with users and locations sorted by commtis
        """
        rawContributionsSQL = s.sql.text("""
            SELECT users.login, users.location, COUNT(*) AS "commits"
            FROM commits
            JOIN project_commits
            ON commits.id = project_commits.commit_id
            JOIN users
            ON users.id = commits.author_id
            WHERE project_commits.project_id = :repoid
            AND LENGTH(users.location) > 1
            GROUP BY users.id
            ORDER BY commits DESC
        """)
        return pd.read_sql(rawContributionsSQL, self.db, params={"repoid": str(repoid)})


    def issue_response_time(self, repoid):
        """
        How long it takes for issues to be responded to by people who have commits associate with the project

        :param repoid: The id of the project in the projects table.
        :return: DataFrame with the issues' id the date it was
                 opened, and the date it was first responded to
        """
        issuesSQL = s.sql.text("""
            SELECT issues.created_at               AS "created_at",
                   MIN(issue_comments.created_at)  AS "responded_at"
            FROM issues
            JOIN issue_comments
            ON issue_comments.issue_id = issues.id
            WHERE issue_comments.user_id IN
                (SELECT users.id
                FROM users
                JOIN commits
                WHERE commits.author_id = users.id
                AND commits.project_id = :repoid)
            AND issues.repo_id = :repoid
            GROUP BY issues.id
        """)
        return pd.read_sql(issuesSQL, self.db, params={"repoid": str(repoid)})

    def linking_websites(self, repoid):
        """
        Finds the repo's popularity on the internet

        :param repoid: The id of the project in the projects table.
        :return: DataFrame with the issues' id the date it was
                 opened, and the date it was first responded to
        """

        # Get the url of the repo
        repo_url_query = s.sql.text('SELECT projects.url FROM projects WHERE projects.id = :repoid')
        repo_url = ''
        result = self.db.execute(repo_url_query, repoid=repoid)
        for row in result:
            repo_url = row[0]

        # Find websites that link to that repo
        query = '<a+href%3D"{repourl}"'.format(repourl=url.quote_plus(repo_url.replace('api.', '').replace('repos/', '')))
        r = 'https://publicwww.com/websites/{query}/?export=csv&apikey={apikey}'.format(query=query, apikey=self.PUBLIC_WWW_API_KEY)
        result =  pd.read_csv(r, delimiter=';', header=None, names=['url', 'rank'])
        return result

    def pull_acceptance_rate(self, repoid):
        """
        Timeseries of pull request acceptance rate (Number of pull requests merged on a date over Number of pull requests opened on a date)

        :param repoid: The id of the project in the projects table.
        :return: DataFrame with the pull acceptance rate and the dates
        """

        pullAcceptanceSQL = s.sql.text("""

        SELECT DATE(date_created) AS "date", CAST(num_approved AS DECIMAL)/CAST(num_open AS DECIMAL) AS "rate"
        FROM
            (SELECT COUNT(DISTINCT pull_request_id) AS num_approved, DATE(pull_request_history.created_at) AS accepted_on
            FROM pull_request_history
            JOIN pull_requests ON pull_request_history.pull_request_id = pull_requests.id
            WHERE action = 'merged' AND pull_requests.base_repo_id = :repoid
            GROUP BY accepted_on) accepted
        JOIN
            (SELECT count(distinct pull_request_id) AS num_open, DATE(pull_request_history.created_at) AS date_created
            FROM pull_request_history
            JOIN pull_requests ON pull_request_history.pull_request_id = pull_requests.id
            WHERE action = 'opened'
            AND pull_requests.base_repo_id = :repoid
            GROUP BY date_created) opened
        ON opened.date_created = accepted.accepted_on
        """)

        return pd.read_sql(pullAcceptanceSQL, self.db, params={"repoid": str(repoid)})

    # ----- Added endpoints -----

        # -- Milestone 3 endpoints --

    def average_issue_response_time(self, repoid):
        """
        The average time it takes for issues to be responded to by people who have commits associate with the project

        :param repoid: The id of the project in the projects table.
        :return: DataFrame with the issues' id the date it was
                 opened, and the date it was first responded to
        """
        avgissuesSQL = s.sql.text("""
            SELECT avg(time_to_member_comment_in_days) as avg_days_to_member_comment, MAX(time_to_member_comment_in_days) as max_days_to_member_comment, MIN(time_to_member_comment_in_days) as min_days_to_member_comment, project_name, url
            FROM
            (
            SELECT DATEDIFF(earliest_member_comment, issue_created) time_to_member_comment_in_days, project_id, issue_id, project_name, url
            FROM
            (SELECT projects.id as project_id,
                    MIN(issue_comments.created_at) as earliest_member_comment,
                    issues.created_at as issue_created,
                    issues.id as issue_id, projects.name as project_name, url
            FROM projects
                join project_members on projects.id = project_members.repo_id
                join issues on issues.repo_id = projects.id
                join issue_comments on issue_comments.issue_id = issues.id
            where issue_comments.user_id = project_members.user_id
            and projects.id = :repoid
            group by issues.id) as earliest_member_comments) as time_to_member_comment
            group by project_id
        """)
        return pd.read_sql(avgissuesSQL, self.db, params={"repoid": str(repoid)})

    def relative_activity(self, repoid):
        """
        The number of contributions from project members vs the number of contributions from other users.
        See "Relative Activity" in OSS Health Metrics wiki:
        https://wiki.linuxfoundation.org/oss-health-metrics/metrics

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with number of project members, total contributions of all project members,
        total contributions of non-project members, and the ratio of pm_contributions / non-pm_contributions.
        """
        relactSQL = s.sql.text("""
        select
	(select count(user_id) from project_members where repo_id = :repoid) as total_contributors
    , ((select count(id) from commits where project_id = :repoid and author_id in (select user_id from project_members where repo_id = :repoid)) +
	(select count(id) from issues where repo_id = :repoid and reporter_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(ic.comment_id) from issue_comments as ic, issues as i
		where ic.issue_id = i.id and i.repo_id = :repoid and ic.user_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(id) from pull_requests where (base_repo_id = :repoid or head_repo_id = :repoid)
		and user_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(pc.comment_id) from pull_request_comments as pc, pull_requests as pr
		where pc.pull_request_id = pr.id and (pr.base_repo_id = :repoid or pr.head_repo_id = :repoid)
        and pc.user_id in (select user_id from project_members where repo_id = :repoid))) as total_pm_contributions
	, ((select count(id) from commits where project_id = :repoid and not author_id in (select user_id from project_members where repo_id = :repoid)) +
	(select count(id) from issues where repo_id = :repoid and not reporter_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(ic.comment_id) from issue_comments as ic, issues as i
		where ic.issue_id = i.id and i.repo_id = :repoid and not ic.user_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(id) from pull_requests where (base_repo_id = :repoid or head_repo_id = :repoid)
		and not user_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(pc.comment_id) from pull_request_comments as pc, pull_requests as pr
		where pc.pull_request_id = pr.id and (pr.base_repo_id = :repoid or pr.head_repo_id = :repoid)
        and not pc.user_id in (select user_id from project_members where repo_id = :repoid))) as total_nonpm_contributions
	, (((select count(id) from commits where project_id = :repoid and author_id in (select user_id from project_members where repo_id = :repoid)) +
	(select count(id) from issues where repo_id = :repoid and reporter_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(ic.comment_id) from issue_comments as ic, issues as i
		where ic.issue_id = i.id and i.repo_id = :repoid and ic.user_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(id) from pull_requests where (base_repo_id = :repoid or head_repo_id = :repoid)
		and user_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(pc.comment_id) from pull_request_comments as pc, pull_requests as pr
		where pc.pull_request_id = pr.id and (pr.base_repo_id = :repoid or pr.head_repo_id = :repoid)
        and pc.user_id in (select user_id from project_members where repo_id = :repoid)))
	/
    ((select count(id) from commits where project_id = :repoid and not author_id in (select user_id from project_members where repo_id = :repoid)) +
	(select count(id) from issues where repo_id = :repoid and not reporter_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(ic.comment_id) from issue_comments as ic, issues as i
		where ic.issue_id = i.id and i.repo_id = :repoid and not ic.user_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(id) from pull_requests where (base_repo_id = :repoid or head_repo_id = :repoid)
		and not user_id in (select user_id from project_members where repo_id = :repoid)) +
    (select count(pc.comment_id) from pull_request_comments as pc, pull_requests as pr
		where pc.pull_request_id = pr.id and (pr.base_repo_id = :repoid or pr.head_repo_id = :repoid)
        and not pc.user_id in (select user_id from project_members where repo_id = :repoid)))) as pm_over_nonpm_ratio
;""")
        return pd.read_sql(relactSQL, self.db, params={"repoid": str(repoid)})

    def relative_activity_pm(self, repoid):
        """
        Breakdown of contributions by project members only.
        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with total commits, issues, issue comments, pull requests, and pull request commments made
        by project members.
        """
        relact_pmSQL = s.sql.text("""
        select
	(select count(user_id) from project_members where repo_id = :repoid) as total_pm_contributors
    , ((select count(id) from commits where project_id = :repoid and author_id in (select user_id from project_members where repo_id = :repoid)) +
		(select count(id) from issues where repo_id = :repoid and reporter_id in (select user_id from project_members where repo_id = :repoid)) +
		(select count(ic.comment_id) from issue_comments as ic, issues as i
			where ic.issue_id = i.id and i.repo_id = :repoid and ic.user_id in (select user_id from project_members where repo_id = :repoid)) +
		(select count(id) from pull_requests where (base_repo_id = :repoid or head_repo_id = :repoid)
			and user_id in (select user_id from project_members where repo_id = :repoid)) +
		(select count(pc.comment_id) from pull_request_comments as pc, pull_requests as pr
			where pc.pull_request_id = pr.id and (pr.base_repo_id = :repoid or pr.head_repo_id = :repoid)
			and pc.user_id in (select user_id from project_members where repo_id = :repoid)))
	as total_pm_contributions
	, (select count(id) from commits where project_id = :repoid and author_id in (select user_id from project_members where repo_id = :repoid))
    as pm_commits
	, (select count(id) from issues where repo_id = :repoid and reporter_id in (select user_id from project_members where repo_id = :repoid))
    as pm_issues
    , (select count(ic.comment_id) from issue_comments as ic, issues as i
		where ic.issue_id = i.id and i.repo_id = :repoid and ic.user_id in (select user_id from project_members where repo_id = :repoid))
	as pm_issue_cmnts
    , (select count(id) from pull_requests where (base_repo_id = :repoid or head_repo_id = :repoid)
		and user_id in (select user_id from project_members where repo_id = :repoid))
	as pm_pullreqs
    , (select count(pc.comment_id) from pull_request_comments as pc, pull_requests as pr
		where pc.pull_request_id = pr.id and (pr.base_repo_id = :repoid or pr.head_repo_id = :repoid)
        and pc.user_id in (select user_id from project_members where repo_id = :repoid))
	as pm_pullreq_cmnts
;""")
        return pd.read_sql(relact_pmSQL, self.db, params={"repoid": str(repoid)})

    def relative_activity_nonpm(self, repoid):
        """
        Breakdown of contributions by non-project members only.
        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with total commits, issues, issue comments, pull requests, and pull request commments made
        by non-project members.
        """
        relact_npmSQL = s.sql.text("""
        select
	(select count(id) from commits where project_id = :repoid and not author_id in (select user_id from project_members where repo_id = :repoid))
    as nonpm_commits
	, (select count(id) from issues where repo_id = :repoid and not reporter_id in (select user_id from project_members where repo_id = :repoid))
    as nonpm_issues
    , (select count(ic.comment_id) from issue_comments as ic, issues as i
		where ic.issue_id = i.id and i.repo_id = :repoid and not ic.user_id in (select user_id from project_members where repo_id = :repoid))
	as nonpm_issue_cmnts
    , (select count(id) from pull_requests where (base_repo_id = :repoid or head_repo_id = :repoid)
		and not user_id in (select user_id from project_members where repo_id = :repoid))
	as nonpm_pullreqs
    , (select count(pc.comment_id) from pull_request_comments as pc, pull_requests as pr
		where pc.pull_request_id = pr.id and (pr.base_repo_id = :repoid or pr.head_repo_id = :repoid)
        and not pc.user_id in (select user_id from project_members where repo_id = :repoid))
	as nonpm_pullreq_cmnts
;""")
        return pd.read_sql(relact_npmSQL, self.db, params={"repoid": str(repoid)})

        # -- Milestone 2 endpoints

    def stargazers_grouped(self, repoid, group_type='WEEK', start=None, end=None):
        """
        Timeseries of when people starred a repo

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :param group_type: Key of member of GROUP_TYPES, otherwise defaults to WEEK on failed lookup
        :return: DataFrame with stargazers per [group_type]
        """
        stargazersSQL = s.sql.text(self.__single_table_count_by_date(
            'watchers', 'repo_id', group_type))
        return pd.read_sql(stargazersSQL, self.db, params={"repoid": str(repoid)})

    def pulls_grouped(self, repoid, group_type):
        """
        Timeseries of pull requests creation, also gives their associated activity

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :param group_type: Member of GROUP_TYPES; specifies how granular the returned data is.
        :return: DataFrame with pull requests grouped by group_type, i.e. year, month, week, or day.
        """
        gt = group_type.upper()
        pullsSQL = s.sql.text("""
                     SELECT date(pull_request_history.created_at) AS "date",
                     (COUNT(pull_requests.id)) AS "pull_requests",
                     (SELECT COUNT(*) FROM pull_request_comments
                     WHERE pull_request_comments.pull_request_id = pull_request_history.pull_request_id) AS "comments"
                     FROM pull_request_history
                     INNER JOIN pull_requests
                     ON pull_request_history.pull_request_id = pull_requests.id
                     WHERE pull_requests.head_repo_id = :repoid
                     AND pull_request_history.action = "merged"
                     GROUP BY {0}(pull_request_history.created_at)
                 """.format(self.convert_group_type(gt)))
        return pd.read_sql(pullsSQL, self.db, params={"repoid": str(repoid)})

    def forks(self, repoid):
        """
        Gets all forks for a repo.  Meant for future UI functionality and reuse within other metrics.

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with forks of the repo.
        """
        forksSQL = s.sql.text("""
        SELECT
            p.id
            , p.name
            , u.login AS fork_owner_name
            , p.forked_from
            , p.created_at
        FROM
            projects AS p
            , users AS u
        WHERE
            p.owner_id = u.id
            AND p.forked_from = :repoid;
        """)
        return pd.read_sql(forksSQL, self.db, params={"repoid": str(repoid)})

    def forks_grouped_default(self, repoid):
        """
        Alias for forks_grouped(repoid, 'WEEK').

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with count of forks created by week.
        """
        return self.forks_grouped(repoid, 'WEEK')

    def issue_actions(self, repoid):
        """
        Gets how many times an action of each type was performed on an issue in the repo.

        :param repoid: The id of the project in the projects table. Use repoid() to get this.
        :return: DataFrame with action name and count of occurrences of that action.
        """
        issueActionsSQL = s.sql.text("""
        SELECT
            DISTINCT action
          , COUNT(action) AS amount
        FROM issue_events
        WHERE issue_id IN (
	      SELECT id
          FROM issues
          WHERE repo_id = :repoid
        )
        GROUP BY action;
        """)
        return pd.read_sql(issueActionsSQL, self.db, params={"repoid": str(repoid)})