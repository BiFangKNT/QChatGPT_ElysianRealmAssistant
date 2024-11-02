from pkg.plugin.context import register, handler, llm_func, BasePlugin, APIHost, EventContext
from pkg.plugin.events import *  # 导入事件类
import yaml
import regex as re
import os
import requests
import time
import base64
import imghdr


# 注册插件
@register(name="ElysianRealmAssistant", description="崩坏3往世乐土攻略助手", version="1.4", author="BiFangKNT")
class ElysianRealmAssistant(BasePlugin):

    # 插件加载时触发
    def __init__(self, host: APIHost):
        super().__init__(host)
        self.config = self.load_config()
        
        self.url_pattern = re.compile(
            rf'''
            ^(?:
                ((.{{0,5}})乐土list) |                        # 匹配0-5个字符后跟"乐土list"
                (乐土推荐\d{{0,2}}) |                         # 匹配"乐土推荐"后跟0-2个数字
                (全部乐土推荐) |                              # 匹配"全部乐土推荐"
                (?P<角色乐土>(.{{1,5}})乐土\d?) |             # 匹配1-5个字符后跟"乐土"，可选择性地跟随一个数字
                (?P<角色流派>(.{{1,5}})(\p{{Han}}{{2}})流)    # 匹配1-5个字符，后跟任意两个中文字符和"流"
            )$
            ''',
            re.VERBOSE | re.UNICODE
        )

    # 异步初始化
    async def initialize(self):
        pass

    @handler(PersonNormalMessageReceived)
    @handler(GroupNormalMessageReceived)
    async def on_message(self, ctx: EventContext):
        await self.ElysianRealmAssistant(ctx)

    def load_config(self):
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(plugin_dir, 'ElysianRealmConfig.yaml')
        
        try:
            with open(config_path, 'r', encoding='utf-8') as file:
                return yaml.safe_load(file)
        except FileNotFoundError:
            self.ap.logger.info(f"配置文件未找到: {config_path}")
            return {}
        except yaml.YAMLError as e:
            self.ap.logger.info(f"解析YAML文件时出错: {e}")
            return {}
        except Exception as e:
            self.ap.logger.info(f"加载配置文件时发生未知错误: {e}")
            return {}

    async def ElysianRealmAssistant(self, ctx: EventContext):

        msg = ctx.event.text_message

        # 输出信息
        self.ap.logger.info(f"乐土攻略助手正在处理消息: {msg}")

        # 如果正则表达式没有匹配成功，直接终止脚本执行
        if not self.url_pattern.search(msg):
            self.ap.logger.info("乐土攻略助手：格式不匹配，不进行处理")
            return

        optimized_message = await self.convert_message(msg, ctx)

        if optimized_message:
            # 输出信息
            self.ap.logger.debug(f"处理后的消息: {optimized_message}")  # 注意：使用base64的话，此项输出会非常长
            
            # 添加重试逻辑
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    ctx.add_return('reply', optimized_message)
                    self.ap.logger.info("消息已成功添加到返回队列")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.ap.logger.info(f"发送消息失败，正在重试 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                        time.sleep(1)  # 等待1秒后重试
                    else:
                        self.ap.logger.info(f"发送消息失败，已达到最大重试次数: {str(e)}")

            # 阻止该事件默认行为
            ctx.prevent_default()

            # 阻止后续插件执行
            ctx.prevent_postorder()
        else:
            self.ap.logger.info("消息处理后为空，不进行回复")

    async def convert_message(self, message, ctx):
        # 统一的回复逻辑
        await ctx.reply(mirai.MessageChain([mirai.Plain(f"已收到指令：{message}\n正在为您查询攻略……")]))
        
        if message == "乐土list":
            return [mirai.Plain(yaml.dump(self.config, allow_unicode=True))]
        
        if message == "全部乐土推荐":
            return await self.handle_recommendation(ctx, True)
        
        if "乐土推荐" in message:
            sequence = int(message.split("乐土推荐")[1] or 1)
            return await self.handle_recommendation(ctx, False, sequence)

        if "乐土list" in message:
            return self.handle_list_query(message)
        
        # 其他情况
        return await self.handle_normal_query(message, ctx)

    async def handle_recommendation(self, ctx, is_all=False, sequence=1):
        url = "https://bbs-api.miyoushe.com/post/wapi/getPostFullInCollection?collection_id=1060106&gids=1&order_type=2"
        
        try:
            # 发送GET请求获取JSON数据
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            # 获取第二张图片的URL
            posts = data.get("data", {}).get("posts", [])
            if posts:
                images = posts[0].get("post", {}).get("images", [])
                subject = posts[0].get("post", {}).get("subject", "")
                reply_time = posts[0].get("post", {}).get("reply_time", "") 
                if len(images) > 1:
                    if 1 <= sequence < len(images):
                        image_url = images[sequence]  # sequence 直接对应图片索引
                    else:
                        self.ap.logger.info(f"序号超出范围，序号为：{sequence}")
                        return [mirai.Plain(f"序号超出范围，请输入1至{len(images) - 1}之间的序号。")]
                    image_data = await self.get_image(image_url, ctx)
                    if image_data and isinstance(image_data, mirai.Image):
                        if is_all:
                            image_urls = images[2:]  # 从第三张图片开始到最后的所有图片URL
                            return [
                                mirai.Plain(f"标题：{subject}\n更新时间：{reply_time}\n本期乐土推荐为：\n"),
                                image_data,
                                mirai.Plain("\n" + "\n".join(image_urls))  # 将所有URL用换行符连接
                            ]
                        else:
                            return [
                                mirai.Plain(f"标题：{subject}\n更新时间：{reply_time}\n本期乐土推荐为：\n"),
                                image_data
                            ]
        
        except Exception as e:
            self.ap.logger.info(f"获取推荐攻略时发生错误: {str(e)}")
            return [mirai.Plain("获取推荐攻略失败。")]

    def handle_list_query(self, message):
        query = message.replace("乐土list", "").strip()
        matched_pairs = {}
        for key, values in self.config.items():
            if any(query in value for value in values):  # 检查是否在任何一个值中
                self.ap.logger.info(f"找到匹配: {key}: {values}")
                matched_pairs[key] = values
        
        if matched_pairs:
            return [mirai.Plain(yaml.dump(matched_pairs, allow_unicode=True))]
        return [mirai.Plain("未找到相关的乐土list信息。")]

    async def handle_normal_query(self, message, ctx):
        for key, values in self.config.items():
            if message in values:
                image_url = f"https://raw.githubusercontent.com/BiFangKNT/ElysianRealm-Data/refs/heads/master/{key}.jpg"
                image_data = await self.get_image(image_url, ctx)
                if image_data and isinstance(image_data, mirai.Image):
                    return [
                        mirai.Plain("已为您找到攻略：\n"),
                        image_data
                    ]
        return [mirai.Plain("未找到相关的乐土攻略。")]

    async def get_image(self, url, ctx):
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                # 方法1：使用Base64编码
                image_base64 = base64.b64encode(response.content).decode('utf-8')
                return mirai.Image(base64=image_base64)

                # 方法2：使用URL
                # return mirai.Image(url=url)

                # 方法3：下载到本地并验证
                # plugin_dir = os.path.dirname(os.path.abspath(__file__))
                # cache_dir = os.path.join(plugin_dir, 'cache')
                # os.makedirs(cache_dir, exist_ok=True)
                # local_path = os.path.join(cache_dir, f"{filename}.jpg")
                # with open(local_path, 'wb') as f:
                #     f.write(response.content)
                # if imghdr.what(local_path) == 'jpeg':
                #     self.ap.logger.info(f"图片已下载到本地并验证: {local_path}")
                #     return mirai.Image(path=local_path)
                # else:
                #     self.ap.logger.warning(f"下载的文件不是有效的JPEG图片: {local_path}")
                #     return None
            else:
                self.ap.logger.info(f"下载图片失败，状态码: {response.status_code}")
                await ctx.reply(mirai.MessageChain([mirai.Plain(f"图片下载失败，状态码: {response.status_code}")]))
        except Exception as e:
            self.ap.logger.info(f"获取图片时发生错误: {str(e)}")
        return None

    # 插件卸载时触发
    def __del__(self):
        pass