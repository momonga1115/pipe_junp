from pathlib import Path                                      # ファイルやフォルダの場所を扱う標準ライブラリ
from kivymd.app import MDApp as App                           # kivyアプリの土台となるクラス
from kivy.uix.widget import Widget                            # 画面に置ける「何もない箱」のようなもの
from kivy.uix.image import Image                              # 画面を表示するための部品
from kivy.core.window import Window                           # ウインドウの大きさ等を扱うもの
from kivy.properties import BooleanProperty, NumericProperty  # キャラの「向き」などを状態として持つために使います
from kivy.core.audio import SoundLoader                       # 音声ファイルを扱うためのもの
from kivy.clock import Clock
from kivy.graphics import PushMatrix, PopMatrix, Scale, Translate, Canvas

'''
【ポイント】
横衝突判定のループの中に、1フレーム1回でよい重力・縦移動・接地判定まで入っていたため、
障害物の数だけ物理更新が繰り返され、ジャンプが不自然になっていました。
今回は元コードを消さず、問題箇所を残したうえで、正しい配置を下に示しています。
'''


#----------------------------------------------
# 画像ファイルが入っているフォルダへの「道」を作る
#----------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

# assets/img フォルダまでのパスを組み立てる
ASSETS_DIR = BASE_DIR / 'assets'
IMG_DIR = ASSETS_DIR / 'img'
BGM_DIR = ASSETS_DIR / 'bgm'


def first_existing(*candidates: Path) -> str:

    for p in candidates:
        if p.is_file():  # 実際にそのファイルが存在するか
            return str(p)

    # 処理がここに来ている時点でファイルが存在しなかったことになる
    raise FileNotFoundError(
        "必要なファイルが見つかりません。assets/img と bgm を確認してください。"
    )


def find_bgm() -> str:
    """BGMファイルを探す
    優先順位
    bgm.ogg / bgm.mp3 / bgm.wav
    main.ogg / main.mp3 / main.wav
    の順に「見つかったもの」を1つ選びます。
    """
    candidates = []
    for stem in ('bgm', 'main'):
        for ext in ('ogg', 'mp3', 'wav'):
            candidates.append(BGM_DIR / f'{stem}.{ext}')
    return first_existing(*candidates)


#----------------------------------------------
# 背景画像 + 雲 + 土管 + レンガ + 主人公 を表示する
#----------------------------------------------
class StageWithJumpGravity(Widget):

    # 横移動＆横衝突に加え、ジャンプ、重力、床停止を実装するステージ

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # 縦方向の速度（ジャンプ、落下に使用）
        self.vy = 0.0

        # 重力の強さ（1秒あたりにどれだけ下向きに加速するか）
        self.gravity = 900.0

        # ジャンプの初速
        self.jump_power = 450.0

        # 地面やブロックの上に立っているか
        self.on_ground = False

        # 背景画像と雲画像のパスを探す
        # bg.png か bg.jpg のどちらでも対応できるようにする
        bg_path = first_existing(IMG_DIR / 'bg.png', IMG_DIR / 'bg.jpg')
        cloud_path = first_existing(IMG_DIR / 'cloud.png')
        dokan_path = first_existing(IMG_DIR / 'dokan.png')
        brick_path = first_existing(IMG_DIR / 'brick_block.png')

        # まずは背景を一番下に敷きます
        bg = Image(
            source=bg_path,         # 探してきた画像ファイル
            allow_stretch=True,     # 画像を引き伸ばすことを許可
            keep_ratio=False,       # 縦横比（アスペクト比）は気にしない
            size=Window.size,       # ★ ウインドウと同じサイズにする
            size_hint=(None, None), # 親（画面全体）に対して「全体いっぱい」
            pos=(0, 0),             # 左下から表示
        )
        self.add_widget(bg)

        # 雲をいくつか配置する
        # size_hint を None にして、ピクセルサイズを直接指定する。
        cloud_positions = [
            (80, 360),
            (420, 420),
            (620, 360),
        ]
        for x, y in cloud_positions:
            cloud = Image(
                source=cloud_path,
                size=(250, 96),
                pos=(x, y),
                size_hint=(None, None),
            )
            self.add_widget(cloud)

        # 土管を一つ置く
        # ここでは「画面の左から 550px の位置」に配置しています。
        self.pipe = Image(
            source=dokan_path,
            size=(64, 96),
            pos=(550, 75),
            size_hint=(None, None),
        )
        self.add_widget(self.pipe)

        # レンガブロックを横一列に並べる(当たり判定あり)
        # 「for ループで少しずつ x 座標をずらす」
        brick_y = 200
        brick_w, brick_h = 32, 32
        base_x = 300

        # レンガを複数まとめて扱えるように list にする
        self.bricks = []

        for i in range(4):
            x = base_x + i * brick_w

            # ブロックの配置位置決め
            # self.brick を毎回上書きしても今回の実害は小さいですが、
            # 「最後の1個だけ属性として残る」ので、ローカル変数 brick の方が自然です。
            brick = Image(
                source=brick_path,
                size=(brick_w, brick_h),
                pos=(x, brick_y),
                size_hint=(None, None),
            )
            self.add_widget(brick)
            self.bricks.append(brick)

        # ① floor を先に作る（基準）
        self.floor = Widget()
        self.floor.size = (Window.width, 80)
        self.floor.pos = (0, 0)
        self.add_widget(self.floor)

        # ② その上にマリオを置く
        self.mario = Mario()
        self.mario.x = 120
        self.mario.y = self.floor.top
        self.add_widget(self.mario)

        # キーの状態（押されている間 True になる）
        self.key_left = False
        self.key_right = False

        # キー入力イベントを受け取れるように登録する
        Window.bind(on_key_down=self.on_key_down, on_key_up=self.on_key_up)

        # 1/60秒ごとに update() を呼んで主人公を動かす
        Clock.schedule_interval(self.update, 1 / 60.0)

    #-----------------------------
    # キー入力処理
    #-----------------------------
    def on_key_down(self, window, key, scancode, codepoint, modifiers):
        '''
        キーが押された時に呼ばれる関数

        key には「キーの番号」が入ってくる
        ここでは、矢印の番号だけを使う
        ・左矢印：276
        ・右矢印：275
        ・SPACE：32
        '''
        if key == 276:   # 左
            self.key_left = True
        elif key == 275: # 右
            self.key_right = True
        elif key == 32:  # SPACE
            # 地面・ブロック・土管などの上にいるときだけジャンプできるようにする
            if self.on_ground:
                self.vy = self.jump_power
                self.on_ground = False

                # ジャンプ開始が見やすいように、少しだけ上に移動させる
                self.mario.y += 4

        return True      # イベントを「ここで終了済み」と伝える

    def on_key_up(self, window, key, scancode):
        '''キーが離された時に呼ばれる関数'''
        if key == 276:
            self.key_left = False
        elif key == 275:
            self.key_right = False
        return True

    #-----------------------------
    # 毎フレーム呼ばれる update
    #-----------------------------
    def update(self, dt: float):
        '''
        1/60秒ごとに呼ばれる
        dt には「前回からの経過時間（秒）」が渡されるので、
        speed（ピクセル/秒）* dt（秒）で移動量を計算します
        '''

        solids = [self.pipe] + self.bricks  # 壁として扱うオブジェクトたち

        vx = 0.0

        # 入力に応じて左右の速度を決める
        if self.key_left and not self.key_right:
            vx = -self.mario.speed
            self.mario.face_left()

        elif self.key_right and not self.key_left:
            vx = self.mario.speed
            self.mario.face_right()

        else:
            vx = 0.0

        # 1フレーム分の移動量を計算
        new_x = self.mario.x + vx * dt

        # 画面の左右端で止める（外にはみ出さないようにする）
        new_x = max(0, min(new_x, Window.width - self.mario.width))

        # 計算した位置を反映
        self.mario.x = new_x

        #------------------------------------------
        # まひろくんの元コード（消さずに残す）
        #------------------------------------------
        # 【指摘】
        # ここで「重力」「縦移動」「接地判定」まで
        # for solid in solids: の内側に入れてしまうと、
        # solids の数だけ1フレーム中に物理更新が繰り返されます。
        #
        # 今回は pipe 1個 + brick 4個 = 合計5個なので、
        # 重力が1フレームに5回近くかかる形になり、
        # ジャンプが不自然に重くなったり、着地判定が乱れたりします。
        #
        # つまり、
        # 「横衝突判定のループ」と
        # 「1フレームに1回だけ行う物理更新」を
        # 分ける必要があります。
        #
        # for solid in solids:
        #     vertical_overlap = (
        #         self.mario.top > solid.y and
        #         self.mario.y < solid.top
        #     )
        #
        #     if vertical_overlap and self.mario.collide_widget(solid):
        #         if vx > 0 and self.mario.right > solid.x:
        #             self.mario.right = solid.x
        #         elif vx < 0 and self.mario.x < solid.right:
        #             self.mario.x = solid.right
        #
        #     # ↓ ここから下をこのループの中に入れてはいけない
        #     self.vy -= self.gravity * dt
        #     self.mario.y += self.vy * dt
        #
        #     if self.vy > 0:
        #         self.mario.set_jump(True)
        #     else:
        #         self.mario.set_jump(False)
        #
        #     self.on_ground = False
        #
        #     if self.mario.y <= self.floor.top:
        #         self.mario.y = self.floor.top
        #         self.vy = 0
        #         self.on_ground = True
        #
        #     for solid in solids:
        #         if self.mario.collide_widget(solid):
        #             if self.vy < 0 and self.mario.y <= solid.y + solid.height:
        #                 self.mario.y = solid.y + solid.height
        #                 self.vy = 0
        #                 self.on_ground = True

        #------------------------------------------
        # 修正版：横衝突だけを先に処理する
        #------------------------------------------
        for solid in solids:
            vertical_overlap = (
                self.mario.top > solid.y and
                self.mario.y < solid.top
            )

            if vertical_overlap and self.mario.collide_widget(solid):
                # 右方向に移動していた場合：壁の左側で止める
                if vx > 0 and self.mario.right > solid.x:
                    self.mario.right = solid.x

                # 左方向に移動していた場合：壁の右側で止める
                elif vx < 0 and self.mario.x < solid.right:
                    self.mario.x = solid.right

        #------------------------------------------
        # 修正版：ここから下は「1フレームに1回だけ」行う物理更新
        #------------------------------------------

        # 先生コメント：
        # 重力は「壁の数」ではなく、「時間の経過」に応じて1回だけかかるべきです。
        self.vy -= self.gravity * dt

        # 先生コメント：
        # 縦方向の移動も1回だけ反映します。
        self.mario.y += self.vy * dt

        # 先生コメント：
        # 上向きに動いている間だけジャンプ画像へ切り替えます。
        if self.vy > 0:
            self.mario.set_jump(True)
        else:
            self.mario.set_jump(False)

        # 先生コメント：
        # 接地状態は毎フレームいったん False に戻し、
        # このあと床やブロックに乗っていたら True にし直します。
        self.on_ground = False

        #------------------------------------------
        # 床との衝突
        #------------------------------------------
        if self.mario.y <= self.floor.top:
            self.mario.y = self.floor.top
            self.vy = 0
            self.on_ground = True

        #------------------------------------------
        # 上に乗る処理（縦方向の衝突）
        #------------------------------------------
        # 先生コメント：
        # 落下中だけ、「上から乗る」判定を許可します。
        # これも1フレームに1回の物理更新の流れの中で行います。
        for solid in solids:
            if self.mario.collide_widget(solid):
                if self.vy < 0 and self.mario.y <= solid.y + solid.height:
                    self.mario.y = solid.y + solid.height
                    self.vy = 0
                    self.on_ground = True


class Mario(Image):
    speed = NumericProperty(220.0)
    facing_left = BooleanProperty(False)

    def __init__(self, **kwargs):
        # 画像パスをプロパティとして保持
        self.walk_texture = first_existing(IMG_DIR / 'mario.png')
        self.jump_texture = first_existing(IMG_DIR / 'mario_jump.png')

        super().__init__(
            source=self.walk_texture,
            size=(64, 64),
            size_hint=(None, None),
            **kwargs
        )

        self._flipped = False

        with self.canvas.before:
            self._push = PushMatrix()
            self._translate = Translate(0, 0, 0)
            self._scale = Scale(1, 1, 1)
        with self.canvas.after:
            self._pop = PopMatrix()

    def set_jump(self, jumping: bool):
        '''ジャンプ中かどうかで画像を切り替える'''
        if jumping:
            if self.source != self.jump_texture:
                self.source = self.jump_texture
        else:
            if self.source != self.walk_texture:
                self.source = self.walk_texture

    def face_left(self):
        """キャラを左向きにする"""
        # すでに左向きなら何もしない（無駄な反転を防ぐ）
        if not self._flipped:
            # x方向を -1 にスケール → 左右反転
            self._scale.x = -1

            # 反転すると描画原点がずれるため、
            # 位置補正として「現在位置 + 幅」だけ平行移動
            self._translate.x = self.x + self.width

            self._flipped = True

    def face_right(self):
        """キャラを右向きにする"""
        # 左向きのときだけ元に戻す
        if self._flipped:
            # 通常スケール（反転解除）
            self._scale.x = 1

            # 平行移動も元に戻す
            self._translate.x = 0

            self._flipped = False

    def on_pos(self, *args):
        """
        位置が変わったときに自動で呼ばれる（Kivyのイベント）
        反転中は、移動に合わせて補正を再計算する。
        """
        if self._flipped:
            # center_x を基準に再計算しないと、
            # 移動時にズレが発生する
            self._translate.x = self.center_x * 2
            self._scale.x = -1
        else:
            self._translate.x = 0
            self._scale.x = 1


#----------------------------------------------
# アプリ本体
#----------------------------------------------
class Step09JumpGravityApp(App):

    def build(self):
        # ウインドウの初期サイズを決める
        Window.size = (800, 540)

        # ウインドウに表示するタイトル（左上にでる）
        self.title = 'Pipe & Jump - Step09 JumpGravity'

        # 先程作った画面を、最初の画面として返す
        return StageWithJumpGravity()

    def on_start(self):
        '''アプリ起動時に自動的にこの関数が呼ばれます。ここでBGMを鳴らします'''
        try:
            bgm_path = find_bgm()
        except FileNotFoundError as e:
            # BGMがなくてもゲームは動いてほしいので、エラーを表示するだけにして止めません。
            print(e)
            return

        self.bgm = SoundLoader.load(bgm_path)
        if self.bgm:
            self.bgm.loop = True  # ループ再生を有効にする
            self.bgm.play()       # BGMを再生する
        else:
            print('BGMを読み込めませんでした。ファイル形式やパスを確認してください。')

    def on_stop(self):
        '''アプリ終了時に自動的にこの関数が呼ばれます。ここでBGMを止めます'''
        if self.bgm:
            self.bgm.stop()


if __name__ == '__main__':
    Step09JumpGravityApp().run()