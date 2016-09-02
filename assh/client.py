#-*- coding: utf-8 -*-

import boto3

class AWSCli(object):

    def __init__(self, aws_region, aws_key, aws_secret, aws_security_token=None):
        self.aws_key = aws_key
        self.aws_secret = aws_secret
        self.aws_token = aws_security_token

        self.session = boto3.Session(aws_access_key_id=self.aws_key,
                                aws_secret_access_key=self.aws_secret,
                                aws_session_token=self.aws_token)
        self.igw = {}

    def get_instances(self, region, tags=None):
        """

        :param region:
        :param aws_key:
        :param aws_secret:
        :param tags: is a dictionary, eg: {'Name': 'App1'}
        :return:
        """

        ec2 = self.session.resource('ec2')
        filters = []
        if tags:
            for tn, tv in self.tags.iteritems():
                filters.append({'Name': tn, 'Values': [tv]})
        filters.append({'Name': 'instance-state-name', 'Values': ['running']})

        instances = ec2.instances.filter(Filters=filters)
        return instances

    def get_nat(self, instance):
        ec2 = self.session.resource('ec2')
        nat_ip = None
        nat_key = None
        if not instance.public_ip_address:
            if instance.vpc_id not in self.igw:
                for routes in instance.vpc.route_tables.all():
                    for route in routes.routes:
                        if route.instance_id:
                            nat_instance = route.instance_id
                            nat_instance = ec2.Instance(nat_instance)
                            nat_ip = nat_instance.public_ip_address
                            nat_key = nat_instance.key_name
                            self.igw[instance.vpc_id] = (nat_ip, nat_key)
                            break
            else:
                nat_ip, nat_key = self.igw[i.vpc_id]
        return nat_ip, nat_key

    def get_instance(self, instance_id):
        ec2 = self.session.resource('ec2')
        instance = ec2.Instance(instance_id)
        return instance
        
