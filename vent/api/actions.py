import ast
import json
import os

from vent.api.plugins import Plugin
from vent.api.templates import Template
from vent.helpers.logs import Logger
from vent.helpers.meta import Version

class Action:
    """ Handle actions in menu """
    def __init__(self, **kargs):
        self.plugin = Plugin(**kargs)
        self.d_client = self.plugin.d_client
        self.vent_config = os.path.join(self.plugin.path_dirs.meta_dir,
                                        "vent.cfg")
        self.logger = Logger(__name__, **kargs)

    def add(self, repo, tools=None, overrides=None, version="HEAD",
            branch="master", build=True, user=None, pw=None, groups=None,
            version_alias=None, wild=None, remove_old=True, disable_old=True):
        """ Add a new set of tool(s) """
        status = (True, None)
        status = self.plugin.add(repo,
                                tools=tools,
                                overrides=overrides,
                                version=version,
                                branch=branch,
                                build=build,
                                user=user,
                                pw=pw,
                                groups=groups,
                                version_alias=version_alias,
                                wild=wild,
                                remove_old=remove_old,
                                disable_old=disable_old)
        return status

    def remove(self, repo=None, namespace=None, name=None, groups=None,
                enabled="yes", branch="master", version="HEAD", built="yes"):
        """ Remove tools or a repo """
        args = locals()
        options = ['name',
                    'namespace',
                    'groups',
                    'enabled',
                    'branch',
                    'built',
                    'version']
        status = (True, None)

        if not repo and not name and not groups and not namespace:
            # at least of these needs to be specified
            status = (False, None)
        else:
            # !! TODO
            # !! TODO if repo, remove the git clone too
            pass

        return status

    def start(self,
             repo=None,
             name=None,
             groups=None,
             enabled="yes",
             branch="master",
             version="HEAD"):
        """
        Start a set of tools that match the parameters given, if no parameters
        are given, start all installed tools on the master branch at verison
        HEAD that are enabled
        """
        args = locals()
        options = ['name',
                  'namespace',
                  'built',
                  'groups',
                  'path',
                  'image_name',
                  'branch',
                  'version']
        # !! TODO needs to be an array of statuses
        status = (True, None)
        vent_config = Template(template=self.vent_config)
        files = vent_config.option('main', 'files')
        sections, template = self.plugin.constraint_options(args, options)
        tool_dict = {}
        for section in sections:
            # initialize needed vars
            template_path = os.path.join(sections[section]['path'], 'vent.template')
            container_name = sections[section]['image_name'].replace(':','-')
            image_name = sections[section]['image_name']

            # checkout the right version and branch of the repo
            self.plugin.branch = branch
            self.plugin.version = version
            cwd = os.getcwd()
            os.chdir(os.path.join(sections[section]['path']))
            status = self.plugin.checkout()
            os.chdir(cwd)

            # ensure tools are built before starting them
            # try and build the tool first
            # !! TODO make this an optional flag (it'll make it easier for testing without merging later
            status = self.build(name=sections[section]['name'],
                               groups=groups,
                               enabled=enabled,
                               branch=branch,
                               version=version)

            # set docker settings for container
            vent_template = Template(template_path)
            status = vent_template.section('docker')
            tool_dict[container_name] = {'image':image_name, 'name':container_name}
            if status[0]:
                for option in status[1]:
                    try:
                        tool_dict[container_name][option[0]] = ast.literal_eval(option[1])
                    except Exception as e: # pragma: no cover
                        tool_dict[container_name][option[0]] = option[1]

            # get temporary name for links, etc.
            # TODO need to get all names for all possible containers
            status = vent_template.section('info')
            if status[0]:
                for option in status[1]:
                    if option[0] == 'name':
                        tool_dict[container_name]['tmp_name'] = option[1]

            # add extra labels
            if 'labels' not in tool_dict[container_name]:
                tool_dict[container_name]['labels'] = {}
            tool_dict[container_name]['labels']['vent'] = Version()
            tool_dict[container_name]['labels']['vent.namespace'] = sections[section]['namespace']
            tool_dict[container_name]['labels']['vent.branch'] = branch
            tool_dict[container_name]['labels']['vent.version'] = version
            tool_dict[container_name]['labels']['vent.name'] = sections[section]['name']

            if 'groups' in sections[section]:
                # add labels for groups
                tool_dict[container_name]['labels']['vent.groups'] = sections[section]['groups']
                # send logs to syslog
                if 'syslog' not in sections[section]['groups'] and 'core' in sections[section]['groups']:
                    tool_dict[container_name]['log_config'] = {'type':'syslog', 'config': {'syslog-address':'tcp://0.0.0.0:514', 'syslog-facility':'daemon', 'tag':'core'}}
                # mount necessary directories
                if 'files' in sections[section]['groups']:
                    if 'volumes' in tool_dict[container_name]:
                        tool_dict[container_name]['volumes'][self.plugin.path_dirs.base_dir[:-1]] = {'bind': '/vent', 'mode': 'ro'}
                    else:
                        tool_dict[container_name]['volumes'] = {self.plugin.path_dirs.base_dir[:-1]: {'bind': '/vent', 'mode': 'ro'}}
                    if files[0]:
                        tool_dict[container_name]['volumes'][files[1]] = {'bind': '/files', 'mode': 'ro'}
            else:
                # !! TODO link logging driver syslog container
                pass

            # add label for priority
            status = vent_template.section('settings')
            if status[0]:
                for option in status[1]:
                    if option[0] == 'priority':
                        tool_dict[container_name]['labels']['vent.priority'] = option[1]

            # !! TODO check for `<command>` and store executed result

            # only start tools that have been built
            if sections[section]['built'] != 'yes':
                del tool_dict[container_name]

        # check and update links, volumes_from, network_mode
        for container in tool_dict.keys():
            if 'links' in tool_dict[container]:
                for link in tool_dict[container]['links']:
                    for c in tool_dict.keys():
                        if 'tmp_name' in tool_dict[c] and tool_dict[c]['tmp_name'] == link:
                            tool_dict[container]['links'][tool_dict[c]['name']] = tool_dict[container]['links'].pop(link)
            if 'volumes_from' in tool_dict[container]:
                # !! TODO
                pass
            if 'network_mode' in tool_dict[container]:
                # !! TODO
                pass

        # remove tmp_names
        for c in tool_dict.keys():
            if 'tmp_name' in tool_dict[c]:
                del tool_dict[c]['tmp_name']

        # check start priorities (priority of groups is alphabetical for now)
        group_orders = {}
        groups = []
        containers_remaining = []
        for container in tool_dict:
            containers_remaining.append(container)
            if 'labels' in tool_dict[container]:
                if 'vent.groups' in tool_dict[container]['labels']:
                    groups += tool_dict[container]['labels']['vent.groups'].split(',')
                    if 'vent.priority' in tool_dict[container]['labels']:
                        priorities = tool_dict[container]['labels']['vent.priority'].split(',')
                        container_groups = tool_dict[container]['labels']['vent.groups'].split(',')
                        for i, priority in enumerate(priorities):
                            if container_groups[i] not in group_orders:
                                group_orders[container_groups[i]] = []
                            group_orders[container_groups[i]].append((int(priority), container))
                        containers_remaining.remove(container)

        # start containers based on priorities
        groups = sorted(set(groups))
        started_containers = []
        for group in groups:
            if group in group_orders:
                for container_tuple in sorted(group_orders[group]):
                    if container_tuple[1] not in started_containers:
                        started_containers.append(container_tuple[1])
                        try:
                            # !! TODO check if container exists and start it instead of run
                            container_id = self.d_client.containers.run(detach=True, **tool_dict[container_tuple[1]])
                            self.logger.info("started "+str(container_tuple[1])+" with ID: "+str(container_id))
                        except Exception as e:
                            self.logger.warning("failed to start "+str(container_tuple[1])+" because: "+str(e))

        # start the rest of the containers that didn't have any priorities set
        for container in containers_remaining:
            try:
                container_id = self.d_client.containers.run(detach=True, **tool_dict[container])
                self.logger.info("started "+str(container)+" with ID: "+str(container_id))
            except Exception as e:
                self.logger.warning("failed to start "+str(container)+" because: "+str(e))

        return status

    @staticmethod
    def update():
        return

    def stop(self,
             repo=None,
             name=None,
             groups=None,
             enabled="yes",
             branch="master",
             version="HEAD"):
        """
        Stop a set of tools that match the parameters given, if no parameters
        are given, stop all installed tools on the master branch at verison
        HEAD that are enabled
        """
        # !! TODO need to account for plugin containers that have random names, use labels perhaps
        args = locals()
        options = ['name',
                  'namespace',
                  'built',
                  'groups',
                  'path',
                  'image_name',
                  'branch',
                  'version']
        sections, template = self.plugin.constraint_options(args, options)
        status = (True, None)
        for section in sections:
            container_name = sections[section]['image_name'].replace(':','-')
            try:
                container = self.d_client.containers.get(container_name)
                container.stop()
                self.logger.info("stopped "+str(container_name))
            except Exception as e:
                self.logger.warning("failed to stop "+str(container_name)+" because: "+str(e))
        return status

    def clean(self,
             repo=None,
             name=None,
             groups=None,
             enabled="yes",
             branch="master",
             version="HEAD"):
        """
        Clean (stop and remove) a set of tools that match the parameters given,
        if no parameters are given, clean all installed tools on the master
        branch at verison HEAD that are enabled
        """
        # !! TODO need to account for plugin containers that have random names, use labels perhaps
        args = locals()
        options = ['name',
                  'namespace',
                  'built',
                  'groups',
                  'path',
                  'image_name',
                  'branch',
                  'version']
        sections, template = self.plugin.constraint_options(args, options)
        status = (True, None)
        for section in sections:
            container_name = sections[section]['image_name'].replace(':','-')
            try:
                container = self.d_client.containers.get(container_name)
                container.remove(force=True)
                self.logger.info("cleaned "+str(container_name))
            except Exception as e:
                self.logger.warning("failed to clean "+str(container_name)+" because: "+str(e))
        return status

    def build(self,
             repo=None,
             name=None,
             groups=None,
             enabled="yes",
             branch="master",
             version="HEAD"):
        """ Build a set of tools that match the parameters given """
        args = locals()
        options = ['image_name', 'path']
        status = (True, None)
        sections, template = self.plugin.constraint_options(args, options)
        for section in sections:
            self.logger.info("Building "+str(section)+" ...")
            template = self.plugin.builder(template, sections[section]['path'],
                                        sections[section]['image_name'],
                                        section, build=True, branch=branch,
                                        version=version)
        template.write_config()
        return status

    @staticmethod
    def backup():
        return

    @staticmethod
    def restore():
        return

    @staticmethod
    def configure():
        # tools, core, etc.
        return

    @staticmethod
    def system_info():
        return

    @staticmethod
    def system_conf():
        return

    @staticmethod
    def system_commands():
        # restart, shutdown, upgrade, etc.
        return

    def logs(self, grep_list=None):
        """ generically filter logs stored in log containers """
        if not grep_list:
            grep_list = {"core"}
        containers = self.d_client.containers.list()
        cores = [c for c in containers if ("core" in c.name)]
        for expression in grep_list:
                for core in cores:
                    try:
                        # 'logs' stores each line which contains the expression
                        logs  = [log for log in core.logs().split("\n") if expression in log]
                        for log in logs:
                            self.logger.info(log)
                    except Exception as e:
                        pass
        return

    @staticmethod
    def help():
        return

    def inventory(self, choices=None):
        # repos, core, tools, images, built, running, etc.
        # plugins that have been added, built, etc.
        items = {}

        try:
            for choice in choices:
                # !! TODO
                items[choice] = ()
        except Exception as e: # pragma: no cover
            pass

        return items
