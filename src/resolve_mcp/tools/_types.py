from typing import Literal

TrackType = Literal["video", "audio", "subtitle"]
Color16 = Literal["Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream"]
MarkerColor = Color16
FlagColor = Color16
ClipColor = Literal["Orange", "Apricot", "Yellow", "Lime", "Olive", "Green", "Teal", "Navy", "Blue", "Purple", "Violet", "Pink", "Tan", "Beige", "Brown", "Chocolate"]
MarkType = Literal["video", "audio", "all"]
Page = Literal["media", "cut", "edit", "fusion", "color", "fairlight", "deliver"]
