# pytest fixtures live here

# 测试环境把 bcrypt 成本因子从生产的 12 降到 4：单次哈希 ~208ms → ~0.8ms。
# 套件中有上百次建用户/登录（每次都跑 hashpw/checkpw），这是纯 CPU 的人为
# 延迟，与被测逻辑无关；test_security.py 只验证哈希正确性与随机盐，不依赖轮数。
# gensalt() 在调用时读取模块级全局，集合阶段改写一次即对所有测试生效；
# 生产入口（CLI/uvicorn）不经过本文件，轮数保持 12 不变。
import myphoto.core.security as _security

_security._BCRYPT_ROUNDS = 4
