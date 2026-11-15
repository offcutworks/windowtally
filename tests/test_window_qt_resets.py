"""The History window's marks for the resets outside the schedule, headless: each kind's marker painted in its own
shape and its account's colour, and the legend outlining each shape it names."""

import unittest

from qt_support import APP

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel

from windowtally import history
from windowtally_gui import plot_view
from windowtally_gui.common_view import Tip, em
from windowtally_gui.plot_model import LinePlot, Marker, Series
from windowtally_gui.plot_view import ChartView, LegendView
from windowtally_gui.theme_view import Theme
from windowtally_gui.theme_model import colours


class ResetMarksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "light")

    def setUp(self):
        self.theme.apply("light")
        self.tip = Tip()
        self.addCleanup(self.tip.close)

    def test_each_kind_s_marker_is_painted_in_its_shape_and_its_account_s_colour(self):
        markers = tuple(Marker(x, 50.0, "series-2", f"a {shape}", shape)
                        for x, shape in ((20.0, "disc"), (50.0, "diamond"), (80.0, "square")))
        plot = LinePlot((Series("alpha", "series-1", ((0.0, 10.0), (100.0, 10.0))),), markers, (0.0, 100.0),
                        (0.0, 100.0), (), ((0.0, "0%"), (100.0, "100%")), None)
        chart = ChartView(self.theme, plot, 12, (), self.tip)
        chart.resize(600, em(12))
        self.addCleanup(chart.deleteLater)
        image = chart.grab().toImage()
        ratio = chart.devicePixelRatio()
        fill = QColor(colours("light")["series-2"]).name()
        dots = [d for d in chart.marks().dots if d.ringed]
        self.assertEqual([d.shape for d in dots], ["disc", "diamond", "square"])
        for dot in dots:
            self.assertEqual(image.pixelColor(round(dot.x * ratio), round(dot.y * ratio)).name(), fill, dot.shape)
        diamond = dots[1]
        # A diamond stands on its point: three quarters of the disc's radius out along both axes lies outside it.
        corner = diamond.radius * 0.75
        self.assertNotEqual(image.pixelColor(round((diamond.x + corner) * ratio),
                                             round((diamond.y + corner) * ratio)).name(), fill)

    def test_a_diamond_and_a_square_have_the_disc_s_area(self):
        radius = 4.0
        for shape in ("diamond", "square"):
            polygon = plot_view.shape_polygon(shape, 0.0, 0.0, radius)
            points = [(polygon.at(i).x(), polygon.at(i).y()) for i in range(polygon.size())]
            area = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]))) / 2
            self.assertAlmostEqual(area, 3.141592653589793 * radius ** 2, places=6, msg=shape)
        self.assertIsNone(plot_view.shape_polygon("disc", 0.0, 0.0, radius))

    def test_the_legend_outlines_each_reset_mark_it_names(self):
        items = (("alpha", "series-1", ""), (history.EXTRA_RESET_NOTE, "ink-2", "disc"),
                 ("Fable's allowance reset", "ink-2", "diamond"), (history.UNKNOWN_RESET_NOTE, "ink-2", "square"))
        legend = LegendView(self.theme, items)
        self.addCleanup(legend.deleteLater)
        self.assertEqual([e.findChild(QLabel).text() for e in legend.entries], [label for label, _r, _m in items])
        self.assertEqual([e.findChild(plot_view.LegendMark).mark for e in legend.entries],
                         ["", "disc", "diamond", "square"])
        for entry in legend.entries:
            entry.findChild(plot_view.LegendMark).grab()   # each paints


if __name__ == "__main__":
    unittest.main()
