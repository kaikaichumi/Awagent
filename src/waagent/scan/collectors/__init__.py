from waagent.scan.collectors.backup import BackupCollector
from waagent.scan.collectors.base import Collector
from waagent.scan.collectors.cloudwatch import CloudWatchCollector
from waagent.scan.collectors.cost import CostCollector
from waagent.scan.collectors.dynamodb import DynamoDbCollector
from waagent.scan.collectors.ec2 import Ec2Collector
from waagent.scan.collectors.elb import ElbCollector
from waagent.scan.collectors.iam import IamCollector
from waagent.scan.collectors.lambda_ import LambdaCollector
from waagent.scan.collectors.rds import RdsCollector
from waagent.scan.collectors.s3 import S3Collector
from waagent.scan.collectors.trusted_advisor import TrustedAdvisorCollector

ALL_COLLECTORS: list[type[Collector]] = [
    Ec2Collector,
    RdsCollector,
    S3Collector,
    IamCollector,
    CloudWatchCollector,
    BackupCollector,
    LambdaCollector,
    ElbCollector,
    DynamoDbCollector,
    CostCollector,
    TrustedAdvisorCollector,
]
